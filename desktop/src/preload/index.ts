import { contextBridge, ipcRenderer } from "electron";

/**
 * 预加载脚本（方案 B M5-a，contextIsolation 下经 contextBridge 注入）。
 *
 * 向渲染层暴露两个全局：
 *   · window.__VIBEBARA_RUNTIME__  —— 运行时配置（对齐前端 VibebaraRuntimeConfig），
 *     前端 getRuntimeConfig() 据此走桌面分支。窗口加载前主进程已就绪，sendSync 取值。
 *   · window.__VIBEBARA_DESKTOP__  —— 桌面专有桥：登录 token 安全存储 + launcher 一键启动 +
 *     deviceId。前端按形态选择（web 形态无此对象 → 走 localStorage / 云端 /launcher）。
 *
 * IPC 通道名与 src/shared/types.ts 的 IPC 常量保持一致（此处用字面量，避免沙箱/打包期
 * 跨文件 require 解析问题）。
 */

const CH = {
  RUNTIME_GET_SYNC: "vibebara:runtime-get-sync",
  TOKEN_GET_SYNC: "vibebara:token-get-sync",
  TOKEN_SET: "vibebara:token-set",
  TOKEN_CLEAR: "vibebara:token-clear",
  LAUNCHER_LIST: "vibebara:launcher-list",
  LAUNCHER_LAUNCH: "vibebara:launcher-launch",
  DEVICE_PERSIST_ID: "vibebara:device-persist-id",
  LOCAL_AGENT_CHANGED: "vibebara:local-agent-changed",
  CLI_AUTHORIZE: "vibebara:cli-authorize",
  UPDATE_GET_STATE: "vibebara:update-get-state",
  UPDATE_CHECK: "vibebara:update-check",
  UPDATE_INSTALL: "vibebara:update-install",
  UPDATE_STATE_CHANGED: "vibebara:update-state-changed",
} as const;

interface RuntimeConfigPayload {
  mode: "desktop";
  cloudApiBase: string;
  cloudWsBase: string;
  localAgentBase: string;
  localAgentPort: number;
  pairingToken: string;
  orchestration: boolean;
  deviceId: string;
  clientUuid: string;
}

interface LocalAgentChangePayload {
  localAgentBase: string;
  localAgentPort: number;
}

interface CliAuthorizationRequest {
  apiKey: string;
  cloudApiBase: string;
}

interface CliAuthorizationResult {
  success: true;
  configPath: string;
  cliBundled: boolean;
  terminalRestartRequired: boolean;
  cliPath?: string;
}

interface DesktopUpdateState {
  status:
    | "disabled"
    | "idle"
    | "checking"
    | "available"
    | "downloading"
    | "downloaded"
    | "error";
  currentVersion: string;
  availableVersion?: string;
  percent?: number;
  transferred?: number;
  total?: number;
  bytesPerSecond?: number;
  message?: string;
}

const runtime =
  (ipcRenderer.sendSync(CH.RUNTIME_GET_SYNC) as RuntimeConfigPayload | null) ??
  null;

// 渲染层进程内同步缓存登录 token（拦截器/路由守卫需同步读）；写时同步更新缓存 + 异步落盘。
let tokenCache: string = (ipcRenderer.sendSync(CH.TOKEN_GET_SYNC) as string) || "";

// 1) 运行时配置（前端 readInjected() 读取此对象）。
contextBridge.exposeInMainWorld("__VIBEBARA_RUNTIME__", runtime ?? {});

// 2) 桌面专有桥。
contextBridge.exposeInMainWorld("__VIBEBARA_DESKTOP__", {
  mode: "desktop",
  deviceId: runtime?.deviceId ?? "",
  clientUuid: runtime?.clientUuid ?? "",
  // M5-b：登录注册后回写云端铸造的规范 device_id（异步落 vibebara-device.json）。
  persistDeviceId: (deviceId: string): Promise<string> =>
    ipcRenderer.invoke(CH.DEVICE_PERSIST_ID, deviceId) as Promise<string>,
  // 任务②：订阅本地代理端口漂移热更（返回取消订阅函数）。
  onLocalAgentChange: (
    cb: (payload: LocalAgentChangePayload) => void,
  ): (() => void) => {
    const listener = (_e: unknown, payload: LocalAgentChangePayload): void =>
      cb(payload);
    ipcRenderer.on(CH.LOCAL_AGENT_CHANGED, listener);
    return () => ipcRenderer.removeListener(CH.LOCAL_AGENT_CHANGED, listener);
  },
  token: {
    /** 同步取当前 token（来自进程内缓存）。 */
    getSync: (): string => tokenCache,
    /** 写 token：更新缓存 + 异步加密落盘。 */
    set: (t: string): void => {
      tokenCache = t || "";
      void ipcRenderer.invoke(CH.TOKEN_SET, tokenCache).catch((error: unknown) => {
        tokenCache = "";
        console.error("[desktop-bridge] 登录凭据安全存储失败:", error);
      });
    },
    /** 清除 token：更新缓存 + 异步删除落盘。 */
    clear: (): void => {
      tokenCache = "";
      void ipcRenderer.invoke(CH.TOKEN_CLEAR).catch((error: unknown) => {
        console.error("[desktop-bridge] 清除登录凭据失败:", error);
      });
    },
  },
  cli: {
    authorize: (request: CliAuthorizationRequest): Promise<CliAuthorizationResult> =>
      ipcRenderer.invoke(
        CH.CLI_AUTHORIZE,
        request,
      ) as Promise<CliAuthorizationResult>,
  },
  launcher: {
    listTools: () => ipcRenderer.invoke(CH.LAUNCHER_LIST),
    launchTool: (req: unknown) => ipcRenderer.invoke(CH.LAUNCHER_LAUNCH, req),
  },
  update: {
    getState: (): Promise<DesktopUpdateState> =>
      ipcRenderer.invoke(CH.UPDATE_GET_STATE) as Promise<DesktopUpdateState>,
    check: (): Promise<DesktopUpdateState> =>
      ipcRenderer.invoke(CH.UPDATE_CHECK) as Promise<DesktopUpdateState>,
    install: (): Promise<boolean> =>
      ipcRenderer.invoke(CH.UPDATE_INSTALL) as Promise<boolean>,
    onStateChange: (
      cb: (payload: DesktopUpdateState) => void,
    ): (() => void) => {
      const listener = (_e: unknown, payload: DesktopUpdateState): void =>
        cb(payload);
      ipcRenderer.on(CH.UPDATE_STATE_CHANGED, listener);
      return () => ipcRenderer.removeListener(CH.UPDATE_STATE_CHANGED, listener);
    },
  },
});
