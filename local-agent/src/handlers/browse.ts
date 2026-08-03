import fs from "node:fs";
import path from "node:path";
import { API_VERSION } from "../constants";
import type { AgentContext } from "../context";
import { AgentError } from "../errors";
import type { BrowseResponse, DirEntry } from "../types";

/**
 * GET /local/browse —— 精确复刻 backend skill_forge_service.browse_directory（:77-123）。
 *
 * 过滤规则：跳过非目录、固定噪声目录及普通隐藏目录；保留 IDE 的点号配置目录，
 * 让用户能浏览并选择 `.cursor/skills`、`.codex/skills` 等 Skill 路径。
 * path 省略/为空：Windows 返回盘符列表，POSIX 返回 "/"。
 *
 * 【M5-b 任务③ 白名单收紧】browse 现为**纯只读浏览，无登记副作用**——消除「看一眼
 * 就扩大白名单」。可写根登记改由「用户确认选定的 deployPath 根」在 write-skill 时绑定
 * （见 handlers/writeSkill.ts），授权来源 = 真正要写的目标目录、而非被动浏览到的目录。
 */
const HIDDEN_DIRS = new Set([
  "node_modules",
  "__pycache__",
  ".git",
  ".svn",
  ".hg",
  "dist",
  "build",
  "$RECYCLE.BIN",
  "System Volume Information",
]);

const VISIBLE_IDE_DOT_DIRS = new Set([
  ".cursor",
  ".codex",
  ".codeium",
  ".claude",
  ".kiro",
  ".trae",
  ".trae-cn",
  ".qoder",
  ".workbuddy",
]);

function listDrivesWindows(): DirEntry[] {
  const drives: DirEntry[] = [];
  for (let i = 65; i <= 90; i++) {
    const letter = String.fromCharCode(i);
    const drive = `${letter}:\\`;
    if (fs.existsSync(drive)) {
      drives.push({ name: `${letter}:`, absPath: drive, isDrive: true });
    }
  }
  return drives;
}

export function handleBrowse(
  pathStr: string | undefined,
  _ctx: AgentContext,
): BrowseResponse {
  // 顶层：空 path → Windows 盘符；POSIX → "/"
  let resolvedInput: string;
  if (!pathStr) {
    if (process.platform === "win32") {
      return {
        ok: true,
        apiVersion: API_VERSION,
        current: "",
        parent: null,
        dirs: listDrivesWindows(),
      };
    }
    resolvedInput = "/";
  } else {
    resolvedInput = pathStr;
  }

  const p = path.resolve(resolvedInput);

  let stat: fs.Stats;
  try {
    stat = fs.statSync(p);
  } catch {
    throw new AgentError("PATH_NOT_FOUND", `路径不存在: ${resolvedInput}`);
  }
  if (!stat.isDirectory()) {
    throw new AgentError("NOT_A_DIRECTORY", `不是目录: ${resolvedInput}`);
  }

  const parentPath = path.dirname(p);
  const parent = parentPath !== p ? parentPath : null;

  // 【任务③】不再登记 current 目录——browse 为纯只读浏览，授权改由 write-skill
  // 的 deployPath（用户确认选定的目标根）绑定。

  let entries: fs.Dirent[];
  try {
    entries = fs.readdirSync(p, { withFileTypes: true });
  } catch {
    // 权限不足：返回空目录列表 + note（对齐 browse_directory PermissionError 分支）
    return {
      ok: true,
      apiVersion: API_VERSION,
      current: p,
      parent,
      dirs: [],
      note: "权限不足",
    };
  }

  // 与后端 sorted(p.iterdir()) 对齐：按名称排序
  entries.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));

  const dirs: DirEntry[] = [];
  for (const entry of entries) {
    let isDir = entry.isDirectory();
    if (entry.isSymbolicLink()) {
      try {
        isDir = fs.statSync(path.join(p, entry.name)).isDirectory();
      } catch {
        isDir = false;
      }
    }
    if (!isDir) continue;
    // 普通隐藏目录仍隐藏；IDE 点号目录必须可见，否则无法从 `.cursor/skills` 等位置导入。
    if (entry.name.startsWith(".") && !VISIBLE_IDE_DOT_DIRS.has(entry.name)) continue;
    if (HIDDEN_DIRS.has(entry.name)) continue;
    const abs = path.join(p, entry.name);
    dirs.push({ name: entry.name, absPath: abs, isDrive: false });
    // 【任务③】不再登记列出的子目录——仅浏览不授权写入。
  }

  return {
    ok: true,
    apiVersion: API_VERSION,
    current: p,
    parent,
    dirs,
  };
}
