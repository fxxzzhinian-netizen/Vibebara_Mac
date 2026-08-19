import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import type {
  LauncherLaunchRequest,
  LauncherLaunchResponse,
  LauncherToolId,
  LauncherToolInfo,
} from "../shared/types";

/**
 * 一键启动工具（方案 B M5-a / 决策 D）。
 *
 * 在 Electron 主进程用 TS 重做原 `backend/app/api/launcher.py` 的命令解析与启动
 * （cursor / codex-cli / codex-app / windsurf）——cloud 形态已下线后端 /launcher 路由，
 * 桌面壳在本机直接启动。经 IPC 暴露给渲染层（见 ipc.ts）。
 *
 * 命令解析口径与 launcher.py 一致：
 *   · cursor   : which(cursor.cmd/cursor) → 后台静默启动；
 *   · codex-cli: which(codex.cmd/codex)   → 新终端窗口启动（交互式）；
 *   · codex-app: 检测新版 ChatGPT（已合并 Codex）并兼容旧 Codex App → 后台启动；
 *   · windsurf : which(windsurf.cmd/windsurf/Windsurf.exe) 或 AppX(Get-StartApps) → 后台启动。
 */

const IS_WINDOWS = process.platform === "win32";
const IS_MAC = process.platform === "darwin";

const SUPPORTED_TOOLS: LauncherToolId[] = [
  "cursor",
  "codex-cli",
  "codex-app",
  "windsurf",
  "claude-code",
  "claude-app",
  "kiro",
  "trae",
  "qoder",
  "workbuddy",
];

const TOOL_LABELS: Record<LauncherToolId, string> = {
  cursor: "Cursor",
  "codex-cli": "Codex CLI",
  "codex-app": "ChatGPT (Codex)",
  windsurf: "Windsurf",
  "claude-code": "Claude Code",
  "claude-app": "Claude",
  kiro: "Kiro",
  trae: "Trae",
  qoder: "Qoder",
  workbuddy: "WorkBuddy",
};

/** 交互式 CLI 工具（新终端窗口启动）；其余按 GUI 应用后台启动。 */
const TERMINAL_TOOLS: ReadonlySet<LauncherToolId> = new Set([
  "codex-cli",
  "claude-code",
]);

/**
 * 「以目标文件夹为工作区打开」的 IDE 工具：仅这些工具才把 project_path 作为命令行参数传入。
 * Codex / Claude 桌面端是对话类应用，不接受工作区路径参数，传入反而会破坏启动（见下）。
 */
const WORKSPACE_TOOLS: ReadonlySet<LauncherToolId> = new Set([
  "cursor",
  "windsurf",
  "kiro",
  "trae",
  "qoder",
  "workbuddy",
]);

/** resolveCommand 结果：cmd 为启动命令数组；viaAppx 表示经 explorer + AppsFolder 协议激活（无法附带任何路径参数）。 */
interface ResolvedCommand {
  cmd: string[];
  viaAppx: boolean;
}

/** 在 PATH 中查找首个可用可执行文件，返回绝对路径或 null（对齐 shutil.which）。 */
function which(...candidates: string[]): string | null {
  for (const name of candidates) {
    try {
      const cmd = IS_WINDOWS ? "where" : "which";
      const r = spawnSync(cmd, [name], { encoding: "utf-8", windowsHide: true });
      if (r.status === 0 && r.stdout) {
        const first = r.stdout
          .split(/\r?\n/)
          .map((s) => s.trim())
          .filter(Boolean)[0];
        if (first) return first;
      }
    } catch {
      /* try next candidate */
    }
  }
  return null;
}

const appxCache = new Map<string, string | null>();

/** Windows：查 MSIX/AppX 安装的应用，返回 shell:AppsFolder URI（对齐 _find_appx_app）。 */
function findAppxApp(pattern: string): string | null {
  if (!IS_WINDOWS) return null;
  if (appxCache.has(pattern)) return appxCache.get(pattern) ?? null;
  try {
    const r = spawnSync(
      "powershell",
      [
        "-NoProfile",
        "-Command",
        `Get-StartApps | Where-Object { $_.Name -like '${pattern}' } | Select-Object -First 1 -ExpandProperty AppID`,
      ],
      { encoding: "utf-8", timeout: 15000, windowsHide: true },
    );
    const appId = (r.stdout ?? "").trim();
    if (appId && r.status === 0) {
      const uri = `shell:AppsFolder\\${appId}`;
      appxCache.set(pattern, uri);
      return uri;
    }
  } catch {
    /* ignore */
  }
  appxCache.set(pattern, null);
  return null;
}

/** 直接可执行文件命令（非 AppX）。 */
function exeCmd(exe: string): ResolvedCommand {
  return { cmd: [exe], viaAppx: false };
}

/** 经 explorer + shell:AppsFolder 协议激活的 AppX 命令（不可附带路径参数）。 */
function appxCmd(uri: string): ResolvedCommand {
  return { cmd: ["explorer.exe", uri], viaAppx: true };
}

const MAC_APP_NAMES: Partial<Record<LauncherToolId, string[]>> = {
  cursor: ["Cursor"],
  "codex-app": ["ChatGPT", "Codex"],
  windsurf: ["Windsurf"],
  "claude-app": ["Claude"],
  kiro: ["Kiro"],
  trae: ["Trae", "TRAE"],
  qoder: ["Qoder"],
  workbuddy: ["WorkBuddy"],
};

/** macOS GUI 应用通常不在 PATH；从标准 Applications 目录发现后交给 `open -a`。 */
function findMacApp(tool: LauncherToolId): ResolvedCommand | null {
  if (!IS_MAC) return null;
  const names = MAC_APP_NAMES[tool] ?? [];
  const roots = [
    "/Applications",
    path.join(os.homedir(), "Applications"),
    "/System/Applications",
  ];
  for (const name of names) {
    if (roots.some((root) => fs.existsSync(path.join(root, `${name}.app`)))) {
      return { cmd: ["open", "-a", name], viaAppx: false };
    }
  }
  return null;
}

/** 解析工具启动命令；未找到抛错。viaAppx=true 表示经 AppsFolder 激活，调用方不得追加任何参数。 */
function resolveCommand(tool: LauncherToolId): ResolvedCommand {
  const macApp = findMacApp(tool);
  if (macApp) return macApp;

  if (tool === "cursor") {
    const exe = IS_WINDOWS ? which("cursor.cmd", "cursor") : which("cursor");
    if (exe) return exeCmd(exe);
    throw new Error("cursor 命令未找到，请确认 Cursor 已安装且在 PATH 中");
  }

  if (tool === "codex-cli") {
    const exe = IS_WINDOWS ? which("codex.cmd", "codex") : which("codex");
    if (exe) return exeCmd(exe);
    throw new Error("codex 命令未找到，请确认 Codex CLI 已安装 (npm i -g @openai/codex)");
  }

  if (tool === "codex-app") {
    if (IS_WINDOWS) {
      // 新版 Codex 已合并进 ChatGPT 客户端；优先识别 ChatGPT，同时兼容旧 Codex App。
      const exe = which(
        "ChatGPT.exe",
        "chatgpt.exe",
        "codex-app.cmd",
        "codex-app",
        "Codex.exe",
      );
      if (exe) return exeCmd(exe);
      const appx =
        findAppxApp("*ChatGPT*") ??
        findAppxApp("*Codex*");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("chatgpt", "ChatGPT", "codex-app", "Codex");
      if (exe) return exeCmd(exe);
    }
    throw new Error("ChatGPT 客户端未找到，请确认已安装包含 Codex 的新版 ChatGPT 客户端");
  }

  if (tool === "windsurf") {
    if (IS_WINDOWS) {
      const exe = which("windsurf.cmd", "windsurf", "Windsurf.exe");
      if (exe) return exeCmd(exe);
      const appx = findAppxApp("Windsurf");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("windsurf", "Windsurf");
      if (exe) return exeCmd(exe);
    }
    throw new Error("windsurf 命令未找到，请确认 Windsurf 已安装且在 PATH 中");
  }

  if (tool === "claude-code") {
    const exe = IS_WINDOWS ? which("claude.cmd", "claude") : which("claude");
    if (exe) return exeCmd(exe);
    throw new Error(
      "claude 命令未找到，请确认 Claude Code 已安装 (npm i -g @anthropic-ai/claude-code)",
    );
  }

  if (tool === "claude-app") {
    if (IS_WINDOWS) {
      const exe = which("claude-app.cmd", "claude-app", "Claude.exe");
      if (exe) return exeCmd(exe);
      const appx = findAppxApp("Claude");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("claude-app", "Claude");
      if (exe) return exeCmd(exe);
    }
    throw new Error("Claude App 未找到，请确认 Claude 桌面应用已安装");
  }

  if (tool === "kiro") {
    if (IS_WINDOWS) {
      const exe = which("kiro.cmd", "kiro", "Kiro.exe");
      if (exe) return exeCmd(exe);
      const appx = findAppxApp("Kiro");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("kiro", "Kiro");
      if (exe) return exeCmd(exe);
    }
    throw new Error("kiro 命令未找到，请确认 Kiro 已安装且在 PATH 中");
  }

  if (tool === "trae") {
    if (IS_WINDOWS) {
      const exe = which("trae.cmd", "trae", "Trae.exe");
      if (exe) return exeCmd(exe);
      // Trae 在开始菜单注册名形态多样（如 "Trae" / "Trae CN" / "TRAE SOLO CN"），用通配匹配
      const appx = findAppxApp("*Trae*");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("trae", "Trae");
      if (exe) return exeCmd(exe);
    }
    throw new Error("trae 命令未找到，请确认 Trae 已安装且在 PATH 中");
  }

  if (tool === "qoder") {
    if (IS_WINDOWS) {
      const exe = which("qoder.cmd", "qoder", "qodercli.cmd", "qodercli", "Qoder.exe");
      if (exe) return exeCmd(exe);
      const appx = findAppxApp("Qoder");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("qoder", "qodercli", "Qoder");
      if (exe) return exeCmd(exe);
    }
    throw new Error("qoder 命令未找到，请确认 Qoder 已安装且在 PATH 中");
  }

  if (tool === "workbuddy") {
    if (IS_WINDOWS) {
      const exe = which("workbuddy.cmd", "workbuddy", "WorkBuddy.exe");
      if (exe) return exeCmd(exe);
      // WorkBuddy（腾讯 CodeBuddy 生态）开始菜单注册名形态多样，用通配匹配
      const appx = findAppxApp("*WorkBuddy*");
      if (appx) return appxCmd(appx);
    } else {
      const exe = which("workbuddy", "WorkBuddy");
      if (exe) return exeCmd(exe);
    }
    throw new Error("workbuddy 命令未找到，请确认 WorkBuddy 已安装且在 PATH 中");
  }

  throw new Error(`不支持的工具: ${tool}`);
}

/** 含空格的参数加引号（Windows shell 命令行拼接用）。 */
function winQuote(s: string): string {
  return /\s/.test(s) ? `"${s}"` : s;
}

/** 后台静默启动（GUI 应用）。 */
function launchBackground(cmd: string[]): void {
  const [bin, ...args] = cmd;
  // Windows 上 .cmd / .bat（如 cursor.cmd、windsurf.cmd）必须经 shell 执行：
  // Node 安全补丁（CVE-2024-27980）后直接 spawn 这类脚本会抛 EINVAL，导致「部署成功但打开失败」。
  if (IS_WINDOWS && /\.(cmd|bat)$/i.test(bin)) {
    const line = [bin, ...args].map(winQuote).join(" ");
    const child = spawn(line, {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
      shell: true,
    });
    child.unref();
    return;
  }
  const child = spawn(bin, args, {
    detached: true,
    stdio: "ignore",
    windowsHide: true,
  });
  child.unref();
}

/**
 * 新终端窗口启动（CLI 交互式工具）。
 * 传入 cwd 时，新终端的工作目录会锁定到该目录（部署后「打开终端并定位到部署目录」）。
 */
function launchTerminal(cmd: string[], cwd?: string): void {
  const workdir = cwd && cwd.trim() ? cwd : undefined;
  if (IS_WINDOWS) {
    // start 一个新控制台运行命令（cmd /k 保留窗口）；/d 指定新窗口的工作目录。
    const startArgs = workdir
      ? ["/c", "start", "", "/d", workdir, "cmd", "/k", ...cmd]
      : ["/c", "start", "cmd", "/k", ...cmd];
    const child = spawn("cmd.exe", startArgs, {
      cwd: workdir,
      detached: true,
      stdio: "ignore",
      windowsHide: false,
    });
    child.unref();
  } else if (IS_MAC) {
    const script = workdir
      ? `cd ${JSON.stringify(workdir)}; ${cmd.join(" ")}`
      : cmd.join(" ");
    spawn("osascript", [
      "-e",
      `tell app "Terminal" to do script "${script.replace(/"/g, '\\"')}"`,
    ]).unref();
  } else {
    for (const term of ["x-terminal-emulator", "gnome-terminal", "xterm"]) {
      if (which(term)) {
        spawn(term, ["-e", ...cmd], {
          cwd: workdir,
          detached: true,
          stdio: "ignore",
        }).unref();
        return;
      }
    }
    spawn(cmd[0], cmd.slice(1), {
      cwd: workdir,
      detached: true,
      stdio: "ignore",
    }).unref();
  }
}

/** 列出所有支持的工具及可用状态（对齐 GET /launcher/tools）。 */
export function listTools(): { tools: LauncherToolInfo[] } {
  const tools: LauncherToolInfo[] = SUPPORTED_TOOLS.map((id) => {
    let available = false;
    try {
      resolveCommand(id);
      available = true;
    } catch {
      available = false;
    }
    let mode: "app" | "terminal";
    let description: string;
    if (id === "codex-cli") {
      mode = "terminal";
      description = "在终端中启动 Codex CLI 交互式对话";
    } else if (id === "codex-app") {
      mode = "app";
      description = "启动包含 Codex 的 ChatGPT 桌面应用";
    } else if (id === "windsurf") {
      mode = "app";
      description = "启动 Windsurf IDE";
    } else if (id === "claude-code") {
      mode = "terminal";
      description = "在终端中启动 Claude Code 交互式对话";
    } else if (id === "claude-app") {
      mode = "app";
      description = "启动 Claude 桌面应用";
    } else if (id === "kiro") {
      mode = "app";
      description = "启动 Kiro IDE";
    } else if (id === "trae") {
      mode = "app";
      description = "启动 Trae IDE";
    } else if (id === "qoder") {
      mode = "app";
      description = "启动 Qoder IDE";
    } else if (id === "workbuddy") {
      mode = "app";
      description = "启动 WorkBuddy IDE";
    } else {
      mode = "app";
      description = "启动 Cursor IDE";
    }
    return { id, label: TOOL_LABELS[id], available, mode, description };
  });
  return { tools };
}

/** 启动工具（对齐 POST /launcher/launch）。 */
export function launchTool(
  req: LauncherLaunchRequest,
): LauncherLaunchResponse {
  const tool = req.tool;
  if (!SUPPORTED_TOOLS.includes(tool)) {
    throw new Error(
      `不支持的工具: ${tool}，可选: ${SUPPORTED_TOOLS.join(", ")}`,
    );
  }

  const { cmd, viaAppx } = resolveCommand(tool);
  const label = TOOL_LABELS[tool];
  const isTerminal = TERMINAL_TOOLS.has(tool);
  const path = (req.project_path ?? "").trim();

  // 路径处理策略（按工具形态）：
  //   · 终端类（codex-cli / claude-code）：路径仅作为新终端的工作目录（cwd），不作为命令行参数；
  //   · IDE 工作区类（cursor / windsurf / ...）：把路径作为参数传入，以该目录为工作区打开；
  //     但经 AppsFolder 激活时（viaAppx）不能附带任何参数，否则 explorer 会去打开该文件夹而非激活应用。
  //   · 桌面对话类（codex-app / claude-app）：不接受工作区路径，仅启动应用本身。
  // —— 这正是「Codex/Claude 桌面端点击后无报错也不启动」的根因：之前对所有工具都把路径
  //     追加到 explorer 命令，导致 AppX 应用无法被激活。
  const appendPath = !isTerminal && WORKSPACE_TOOLS.has(tool) && !viaAppx && !!path;
  if (appendPath) {
    cmd.push(path);
  }

  if (isTerminal) {
    // 终端类工具：把新终端的工作目录锁定到部署目录（project_path）。
    launchTerminal(cmd, path || undefined);
  } else {
    launchBackground(cmd);
  }

  // 仅在路径被实际使用时（终端 cwd / IDE 工作区参数）提示项目路径，避免对桌面对话类应用产生误导。
  const usedPath = isTerminal ? !!path : appendPath;
  const suffix = usedPath ? `，项目路径: ${path}` : "";
  return {
    status: "launched",
    tool,
    mode: isTerminal ? "terminal" : "app",
    message: `${label} 已成功启动${suffix}`,
  };
}
