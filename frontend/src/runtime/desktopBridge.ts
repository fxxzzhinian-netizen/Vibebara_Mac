/**
 * 桌面壳专有桥访问（方案 B M5-a）。
 *
 * M5 Electron 桌面壳通过 preload/contextBridge 在渲染层注入 `window.__VIBEBARA_DESKTOP__`，
 * 提供 web 形态没有的本机能力：
 *   · token：登录 token 的安全存储（OS keychain / safeStorage，替代 localStorage）；
 *   · launcher：一键启动本机 Cursor / Codex（替代 cloud 已下线的 /launcher 路由）；
 *   · deviceId / mode：设备与形态标识。
 *
 * web 形态下该对象不存在（getDesktopBridge() 返回 null），调用方回退到旧行为
 * （localStorage / 云端 /launcher）。前端据此「按形态选择」，保持 web 形态不变。
 */

export type DesktopToolId =
  | 'cursor'
  | 'codex-cli'
  | 'codex-app'
  | 'windsurf'
  | 'claude-code'
  | 'claude-app'
  | 'kiro'
  | 'trae'
  | 'qoder'
  | 'workbuddy'

export interface DesktopToolInfo {
  id: DesktopToolId
  label: string
  available: boolean
  mode: 'app' | 'terminal'
  description: string
}

export interface DesktopLaunchRequest {
  tool: DesktopToolId
  project_path?: string
}

export interface DesktopLaunchResponse {
  status: string
  tool: string
  mode: 'app' | 'terminal'
  message: string
}

/** 本地代理热更负载（端口漂移时主进程经 IPC 推送，M5-b 任务②）。 */
export interface LocalAgentChangePayload {
  localAgentBase: string
  localAgentPort: number
}

export interface CliAuthorizationRequest {
  apiKey: string
  cloudApiBase: string
  userId: string
  deviceId: string
}

export interface CliAuthorizationResult {
  success: true
  configPath: string
  cliBundled: boolean
  terminalRestartRequired: boolean
  cliPath?: string
}

export type DesktopUpdateStatus =
  | 'disabled'
  | 'idle'
  | 'checking'
  | 'available'
  | 'downloading'
  | 'downloaded'
  | 'error'

export interface DesktopUpdateState {
  status: DesktopUpdateStatus
  currentVersion: string
  availableVersion?: string
  percent?: number
  transferred?: number
  total?: number
  bytesPerSecond?: number
  message?: string
}

export interface VibebaraDesktopBridge {
  mode: 'desktop'
  /** 有效设备标识（M5-b）：registeredDeviceId ?? clientUuid。 */
  deviceId: string
  /** 本机持久 uuid（M5-b 设备注册幂等键，非鉴权凭证）。 */
  clientUuid?: string
  /**
   * 回写云端铸造的规范 device_id（M5-b 任务①：登录注册后）。
   * 主进程落 vibebara-device.json.registeredDeviceId + 热更运行时，返回有效 deviceId。
   */
  persistDeviceId?(deviceId: string): Promise<string>
  /**
   * 订阅本地代理端口漂移热更（M5-b 任务②）。返回取消订阅函数。
   * web 形态下该方法不存在（调用方据此跳过）。
   */
  onLocalAgentChange?(cb: (payload: LocalAgentChangePayload) => void): () => void
  token: {
    /** 同步取当前登录 token（来自壳进程内缓存）。 */
    getSync(): string
    /** 写登录 token（safeStorage 加密落盘）。 */
    set(token: string): void
    /** 清除登录 token。 */
    clear(): void
  }
  cli: {
    /** 将当前会话铸造的 PAT 与云端地址写入用户级 CLI 配置。 */
    authorize(req: CliAuthorizationRequest): Promise<CliAuthorizationResult>
    bindIdentity(req: {
      userId: string
      deviceId: string
    }): Promise<{ success: true; cleared: boolean }>
  }
  launcher: {
    listTools(): Promise<{ tools: DesktopToolInfo[] }>
    launchTool(req: DesktopLaunchRequest): Promise<DesktopLaunchResponse>
  }
  update: {
    /** 获取主进程维护的更新状态快照，避免订阅前发生的事件丢失。 */
    getState(): Promise<DesktopUpdateState>
    /** 立即触发一次更新检查。 */
    check(): Promise<DesktopUpdateState>
    /** 退出应用并安装已下载完成的版本。 */
    install(): Promise<boolean>
    /** 订阅检查、下载进度和下载完成状态。 */
    onStateChange(cb: (payload: DesktopUpdateState) => void): () => void
  }
}

declare global {
  interface Window {
    /** M5 桌面壳注入的桌面专有桥（web 形态下为 undefined）。 */
    __VIBEBARA_DESKTOP__?: VibebaraDesktopBridge
  }
}

/** 取桌面专有桥；web 形态返回 null。 */
export function getDesktopBridge(): VibebaraDesktopBridge | null {
  if (typeof window !== 'undefined' && window.__VIBEBARA_DESKTOP__) {
    return window.__VIBEBARA_DESKTOP__
  }
  return null
}

/** 是否运行在桌面壳形态（桥存在即认定为桌面）。 */
export function isDesktop(): boolean {
  return getDesktopBridge() !== null
}
