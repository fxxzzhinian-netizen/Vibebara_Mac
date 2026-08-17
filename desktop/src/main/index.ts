import { app, BrowserWindow, dialog, Menu, protocol, session } from "electron";
import fs from "node:fs/promises";
import path from "node:path";
import {
  checkForDesktopUpdate,
  configureAutoUpdater,
  getUpdateState,
  installDesktopUpdate,
  onUpdateStateChange,
} from "./autoUpdate";
import {
  getEffectiveDeviceId,
  getOrCreateClientUuid,
  persistRegisteredDeviceId,
} from "./deviceId";
import { registerIpc } from "./ipc";
import { LocalAgentManager } from "./localAgentManager";
import { generatePairingToken } from "./pairing";
import { findFreePort } from "./portFinder";
import { buildRuntimeConfig } from "./runtimeConfig";
import { loadCloudConfig } from "./userConfig";
import { IPC, type RuntimeConfigPayload } from "../shared/types";

/**
 * Vibebara 桌面壳主进程入口（方案 B M5-a）。
 *
 * 启动顺序（注入时序关键，§5 风险「注入时序」）：
 *   1. 解析路径（local-agent 入口 / frontend 产物）；
 *   2. 读云端配置、device_id、生成配对令牌、探测空闲端口；
 *   3. 先组装运行时配置 + 注册 IPC（保证窗口加载前 preload sendSync 可取到值）；
 *   4. 拉起本地代理并等待健康（失败不阻塞建窗，代理后台自重启）；
 *   5. 创建窗口加载渲染层。
 * 退出时同步清理本地代理子进程。
 */

const LOCAL_AGENT_PREFERRED_PORT = 51873; // 与 local-agent dev 默认对齐，便于诊断
const FRONTEND_SCHEME = "vibebara";
const FRONTEND_HOST = "app";
const FRONTEND_ENTRY_URL = `${FRONTEND_SCHEME}://${FRONTEND_HOST}/index.html`;

protocol.registerSchemesAsPrivileged([
  {
    scheme: FRONTEND_SCHEME,
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      corsEnabled: true,
    },
  },
]);

let agent: LocalAgentManager | null = null;
let runtimeConfig: RuntimeConfigPayload | null = null;
let mainWindow: BrowserWindow | null = null;
let updateUrl = "";

function resolvePaths(): { agentEntry: string; frontendIndex: string } {
  const isPackaged = app.isPackaged;
  // dev（未打包）：app.getAppPath() = desktop 目录，其上级 = 项目根。
  // packaged：local-agent / frontend 作为 extraResources 放到 resourcesPath（M5-c）。
  const root = isPackaged
    ? process.resourcesPath
    : path.resolve(app.getAppPath(), "..");
  return {
    agentEntry: path.join(root, "local-agent", "dist", "index.js"),
    frontendIndex: path.join(root, "frontend", "dist", "index.html"),
  };
}

function devServerUrl(): string | null {
  const raw = process.env.VIBEBARA_DEV_SERVER_URL;
  if (!raw) return null;
  if (app.isPackaged) {
    throw new Error("安装包禁止加载 VIBEBARA_DEV_SERVER_URL");
  }
  const url = new URL(raw);
  const loopbackHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  if (!["http:", "https:"].includes(url.protocol) || !loopbackHosts.has(url.hostname)) {
    throw new Error("VIBEBARA_DEV_SERVER_URL 仅允许 localhost/127.0.0.1/[::1]");
  }
  return url.href;
}

function normalizedPath(value: string): string {
  const normalized = path.normalize(path.resolve(value));
  return process.platform === "win32" ? normalized.toLowerCase() : normalized;
}

function isPathInside(root: string, candidate: string): boolean {
  const normalizedRoot = normalizedPath(root);
  const normalizedCandidate = normalizedPath(candidate);
  return (
    normalizedCandidate === normalizedRoot ||
    normalizedCandidate.startsWith(`${normalizedRoot}${path.sep}`)
  );
}

const FRONTEND_MIME_TYPES: Record<string, string> = {
  ".css": "text/css; charset=utf-8",
  ".gif": "image/gif",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpeg": "image/jpeg",
  ".jpg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
};

/** 用受信任标准协议承载本地前端，避免 file:// ES Module 被 Chromium CORS 拦截。 */
function configureFrontendProtocol(): void {
  const frontendRoot = path.dirname(resolvePaths().frontendIndex);
  void protocol.handle(FRONTEND_SCHEME, async (request) => {
    try {
      const url = new URL(request.url);
      if (url.hostname !== FRONTEND_HOST) {
        return new Response("Not found", { status: 404 });
      }
      const relativePath =
        decodeURIComponent(url.pathname).replace(/^[/\\]+/, "") || "index.html";
      const target = path.resolve(frontendRoot, relativePath);
      if (!isPathInside(frontendRoot, target)) {
        return new Response("Forbidden", { status: 403 });
      }
      const content = await fs.readFile(target);
      return new Response(new Uint8Array(content), {
        headers: {
          "Content-Type":
            FRONTEND_MIME_TYPES[path.extname(target).toLowerCase()] ??
            "application/octet-stream",
        },
      });
    } catch {
      return new Response("Not found", { status: 404 });
    }
  });
}

/** IPC 与导航只信任内置 vibebara:// 页面，开发态只信任显式本机 Vite origin。 */
function isTrustedRendererUrl(rawUrl: string): boolean {
  try {
    const candidate = new URL(rawUrl);
    const devUrl = devServerUrl();
    if (devUrl) {
      return candidate.origin === new URL(devUrl).origin;
    }
    return (
      candidate.protocol === `${FRONTEND_SCHEME}:` &&
      candidate.hostname === FRONTEND_HOST &&
      candidate.pathname === "/index.html"
    );
  } catch {
    return false;
  }
}

/** 本地代理端口漂移（崩溃重启分到新端口）→ 热更 runtimeConfig + 推送渲染层（M5 任务②）。 */
function onLocalAgentPortChange(port: number): void {
  if (!runtimeConfig) return;
  const localAgentBase = `http://127.0.0.1:${port}`;
  runtimeConfig.localAgentBase = localAgentBase;
  runtimeConfig.localAgentPort = port;
  // 推送渲染层：前端 localAgentClient 动态读取 base，使端口漂移对用户透明。
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send(IPC.LOCAL_AGENT_CHANGED, {
      localAgentBase,
      localAgentPort: port,
    });
  }
  console.log(`[main] 本地代理端口漂移 → ${localAgentBase}（已热更并推送渲染层）`);
}

async function bootstrap(): Promise<void> {
  const { agentEntry } = resolvePaths();
  const cloud = loadCloudConfig();
  updateUrl = cloud.updateUrl;
  const clientUuid = getOrCreateClientUuid();
  const deviceId = getEffectiveDeviceId(); // registeredDeviceId ?? clientUuid
  const pairingToken = generatePairingToken();
  const port = await findFreePort(LOCAL_AGENT_PREFERRED_PORT);

  // 先组装配置 + 注册 IPC：即便本地代理稍后才就绪，注入也能生效。
  runtimeConfig = buildRuntimeConfig({ port, pairingToken, cloud, deviceId, clientUuid });
  registerIpc({
    getRuntimeConfig: () => runtimeConfig,
    isTrustedSender: isTrustedRendererUrl,
    // M5-b：登录注册后回写规范 device_id + 热更运行时（后续 sendSync 即取新值）。
    persistDeviceId: (id: string): string => {
      persistRegisteredDeviceId(id);
      const effective = getEffectiveDeviceId();
      if (runtimeConfig) runtimeConfig.deviceId = effective;
      return effective;
    },
    getUpdateState,
    checkForUpdate: checkForDesktopUpdate,
    installUpdate: installDesktopUpdate,
  });

  console.log(
    `[main] runtime: mode=desktop localAgentPort=${port} cloudApiBase=${cloud.cloudApiBase} ` +
      `cloudWsBase=${cloud.cloudWsBase} clientUuid=${clientUuid.slice(0, 8)}… ` +
      `deviceId=${deviceId.slice(0, 8)}…`,
  );

  agent = new LocalAgentManager({
    agentEntry,
    port,
    pairingToken,
    writableRoots: cloud.writableRoots,
    onLog: (line) => console.log(line),
    // 端口漂移支持（任务②）：重启前重探空闲端口 + 以实际监听端口为准热更。
    findPort: (preferred) => findFreePort(preferred),
    onPortChange: onLocalAgentPortChange,
  });

  try {
    const health = await agent.start();
    console.log(
      `[main] 本地代理就绪 agentVersion=${health.agentVersion} apiVersion=${health.apiVersion} ` +
        `platform=${health.platform} paired=${health.paired}`,
    );
  } catch (e) {
    console.error(
      "[main] 本地代理启动/健康探测失败（将后台自重启）:",
      (e as Error)?.message,
    );
  }
}

/**
 * 网络代理策略：默认强制直连，忽略系统代理。
 *
 * 背景：桌面端只访问自己的云端后端（国内可直连）与本机本地代理（127.0.0.1）。
 * 若跟随系统代理，用户开过全局 VPN（如 Clash/V2Ray，常驻 127.0.0.1:PORT 系统代理）后，
 * 这些云端请求会被强行送进代理：
 *   - VPN 关掉后代理端口失效 → 请求“无响应”（连接失败）；
 *   - 代理按进程/规则改走它路 → 后端/防火墙对该出口拒绝（HTTP 403）。
 * 两者都表现为登录页“验证码加载失败”。强制直连可彻底规避系统代理抖动。
 * 确有需要跟随系统代理时设 VIBEBARA_USE_SYSTEM_PROXY=1 还原。
 */
async function configureProxy(): Promise<void> {
  if (process.env.VIBEBARA_USE_SYSTEM_PROXY === "1") {
    console.log("[main] 代理策略: 跟随系统代理（VIBEBARA_USE_SYSTEM_PROXY=1）");
    return;
  }
  try {
    await session.defaultSession.setProxy({ mode: "direct" });
    console.log("[main] 代理策略: 强制直连（忽略系统代理，规避 VPN 残留代理干扰）");
  } catch (e) {
    console.error("[main] 设置直连代理失败:", (e as Error)?.message);
  }
}

function configureSessionSecurity(): void {
  session.defaultSession.setPermissionCheckHandler(() => false);
  session.defaultSession.setPermissionRequestHandler(
    (_webContents, _permission, callback) => callback(false),
  );
}

function createWindow(): void {
  // 移除 Electron 默认应用菜单（File/Edit/View/Window/Help）：本应用 UI 完全由前端承载，
  // 不需要原生菜单栏。不显式置 null，Electron 会自动挂上内置默认菜单。
  Menu.setApplicationMenu(null);
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 800,
    title: "Vibebara",
    autoHideMenuBar: true,
    // 去掉原生标题栏/顶部边框：隐藏系统标题栏，仅以 overlay 形式保留右上角
    // 最小化/最大化/关闭三个原生窗口按钮（底色与前端顶栏白色一致，图标取主色）。
    // 窗口拖动区域由前端顶栏通过 CSS `-webkit-app-region: drag` 提供（见 AppTopNav.vue）。
    titleBarStyle: "hidden",
    titleBarOverlay: {
      // 取前端画布 bg.png 顶部的浅紫色，让右上角窗口按钮底色融入背景，避免突兀白块。
      color: "#ece8f7",
      symbolColor: "#151717",
      // 高度需与前端 .win-bar 一致（见 frontend/src/components/AppTopNav.vue）。
      height: 40,
    },
    webPreferences: {
      preload: path.join(__dirname, "..", "preload", "index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      webSecurity: true,
      allowRunningInsecureContent: false,
    },
  });

  mainWindow.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!isTrustedRendererUrl(url)) {
      event.preventDefault();
      console.warn(`[security] 已拦截非受信任导航: ${url}`);
    }
  });
  mainWindow.webContents.on("will-attach-webview", (event) => {
    event.preventDefault();
  });

  const devUrl = devServerUrl();
  if (devUrl) {
    void mainWindow.loadURL(devUrl);
  } else {
    void mainWindow.loadURL(FRONTEND_ENTRY_URL);
  }

  mainWindow.on("closed", () => {
    mainWindow = null;
  });
}

function shutdownAgent(): void {
  if (agent) {
    agent.stop();
    agent = null;
  }
}

void app
  .whenReady()
  .then(async () => {
    configureFrontendProtocol();
    await bootstrap();
    await configureProxy();
    configureSessionSecurity();
    createWindow();
    onUpdateStateChange((state) => {
      if (mainWindow && !mainWindow.isDestroyed()) {
        mainWindow.webContents.send(IPC.UPDATE_STATE_CHANGED, state);
      }
    });
    configureAutoUpdater(updateUrl);

    app.on("activate", () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow();
    });
  })
  .catch((error: unknown) => {
    const message = (error as Error)?.message || String(error);
    console.error("[main] 启动失败:", message);
    dialog.showErrorBox("Vibebara 启动失败", message);
    app.quit();
  });

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

// 退出清理：同步杀子进程，杜绝僵尸 node。
app.on("before-quit", shutdownAgent);
app.on("will-quit", shutdownAgent);
process.on("exit", shutdownAgent);
process.on("SIGINT", () => {
  shutdownAgent();
  process.exit(0);
});
process.on("SIGTERM", () => {
  shutdownAgent();
  process.exit(0);
});
