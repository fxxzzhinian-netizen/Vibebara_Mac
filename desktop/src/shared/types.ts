/**
 * 主进程 ↔ 预加载脚本共享的类型与 IPC 通道常量（方案 B M5-a）。
 *
 * RuntimeConfigPayload 的字段**必须**与 `frontend/src/runtime/config.ts` 的
 * `VibebaraRuntimeConfig` 保持一致——这是桌面壳注入渲染层的运行时契约。
 *
 * M5-b 设备身份地基：
 *   · `clientUuid` = 本机持久 uuid（幂等再注册键，非鉴权凭证）；
 *   · `deviceId` = 有效设备标识 = `registeredDeviceId ?? clientUuid`
 *     （登录注册后经桥回写规范 device_id，注入即更新）。
 */

/** 注入到 window.__VIBEBARA_RUNTIME__ 的运行时配置（对齐前端 VibebaraRuntimeConfig）。 */
export interface RuntimeConfigPayload {
  /** 桌面壳固定为 'desktop'（前端据此走桌面分支：orchestration=true）。 */
  mode: "desktop";
  /** 云端 REST API 基址（axios baseURL，含 /api/v1）。先指向本机 cloud demo。 */
  cloudApiBase: string;
  /** 云端 WebSocket 基址（不含路径），如 ws://127.0.0.1:8000。 */
  cloudWsBase: string;
  /** 本地代理基址 http://127.0.0.1:<分配端口>（崩溃重启端口漂移时经 IPC 热更）。 */
  localAgentBase: string;
  /** 本地代理端口（主进程探测的空闲端口；端口漂移时同步更新）。 */
  localAgentPort: number;
  /** 配对令牌（X-Pairing-Token）。主进程生成的高熵令牌。 */
  pairingToken: string;
  /** 桌面壳启用前端多步编排链路。 */
  orchestration: boolean;
  /**
   * 有效设备标识（M5-b）。= registeredDeviceId（云端铸造）?? clientUuid（本机占位）。
   * 前端正式形态用它做平台安装态上报维度键。
   */
  deviceId: string;
  /** 本机持久 uuid（M5-b 设备注册的幂等键，非鉴权凭证）。web 形态下 undefined。 */
  clientUuid: string;
}

/** 本地代理热更负载（端口漂移时主进程经 IPC 推送给渲染层）。 */
export interface LocalAgentChangePayload {
  localAgentBase: string;
  localAgentPort: number;
}

export interface CliAuthorizationRequest {
  apiKey: string;
  cloudApiBase: string;
  userId: string;
  deviceId: string;
}

export interface CliAuthorizationResult {
  success: true;
  configPath: string;
  /** 当前桌面安装包是否携带独立 vibebara.exe。 */
  cliBundled: boolean;
  /** PATH 更新只对新终端生效。 */
  terminalRestartRequired: boolean;
  /** 安装包内 CLI 的绝对路径；开发态缺省。 */
  cliPath?: string;
}

export type DesktopUpdateStatus =
  | "disabled"
  | "idle"
  | "checking"
  | "available"
  | "downloading"
  | "downloaded"
  | "error";

/** 主进程维护并推送给渲染层的桌面更新状态快照。 */
export interface DesktopUpdateState {
  status: DesktopUpdateStatus;
  currentVersion: string;
  availableVersion?: string;
  percent?: number;
  transferred?: number;
  total?: number;
  bytesPerSecond?: number;
  message?: string;
}

/** IPC 通道名（main ↔ preload）。 */
export const IPC = {
  /** 同步取运行时配置（preload sendSync，窗口加载前已就绪）。 */
  RUNTIME_GET_SYNC: "vibebara:runtime-get-sync",
  /** 同步取已持久化登录 token（preload 启动缓存用）。 */
  TOKEN_GET_SYNC: "vibebara:token-get-sync",
  /** 异步写登录 token（safeStorage 加密落盘）。 */
  TOKEN_SET: "vibebara:token-set",
  /** 异步清除登录 token。 */
  TOKEN_CLEAR: "vibebara:token-clear",
  /** 列出可启动工具及可用状态。 */
  LAUNCHER_LIST: "vibebara:launcher-list",
  /** 启动指定工具。 */
  LAUNCHER_LAUNCH: "vibebara:launcher-launch",
  /** 异步回写云端铸造的规范 device_id（M5-b 注册后）。 */
  DEVICE_PERSIST_ID: "vibebara:device-persist-id",
  /** 主进程 → 渲染层推送：本地代理端口漂移（热更 localAgentBase）。 */
  LOCAL_AGENT_CHANGED: "vibebara:local-agent-changed",
  /** 将已认证会话铸造的 PAT 写入 CLI 配置文件。 */
  CLI_AUTHORIZE: "vibebara:cli-authorize",
  /** 登录身份变化时清除上一账号/设备的 CLI PAT。 */
  CLI_BIND_IDENTITY: "vibebara:cli-bind-identity",
  /** 获取当前桌面更新状态快照。 */
  UPDATE_GET_STATE: "vibebara:update-get-state",
  /** 立即检查更新（后台自动检查之外的手动入口）。 */
  UPDATE_CHECK: "vibebara:update-check",
  /** 退出应用并安装已经下载完成的更新。 */
  UPDATE_INSTALL: "vibebara:update-install",
  /** 主进程 → 渲染层推送：更新状态或下载进度变化。 */
  UPDATE_STATE_CHANGED: "vibebara:update-state-changed",
} as const;

export type LauncherToolId =
  | "cursor"
  | "codex-cli"
  | "codex-app"
  | "windsurf"
  | "claude-code"
  | "claude-app"
  | "kiro"
  | "trae"
  | "qoder"
  | "workbuddy";

export interface LauncherToolInfo {
  id: LauncherToolId;
  label: string;
  available: boolean;
  mode: "app" | "terminal";
  description: string;
}

export interface LauncherLaunchRequest {
  tool: LauncherToolId;
  project_path?: string;
}

export interface LauncherLaunchResponse {
  status: string;
  tool: string;
  mode: "app" | "terminal";
  message: string;
}
