/**
 * Vibebara 渲染层运行时配置（方案 B / M4 前端分流）。
 *
 * 背景（M0 §1.1 / §9）：桌面客户端形态下，前端是**唯一编排者**，同时持有
 *   - 云端 Bearer Token（发给云端 FastAPI `/api/v1` + WSS）；
 *   - 本地配对令牌 X-Pairing-Token（发给本地代理 `http://127.0.0.1:PORT`）。
 * 这两套地址/令牌都需要在运行时确定，不能再硬编码 `window.location` 或 `/api/v1`。
 *
 * 配置来源优先级（高 → 低）：
 *   1. `window.__VIBEBARA_RUNTIME__`（M5 桌面壳通过 preload/contextBridge 注入真实值）；
 *   2. Vite 环境变量 `import.meta.env.VITE_*`（构建期注入，便于灰度/分环境）；
 *   3. 安全默认值（web 灰度形态：云端走 `/api/v1` + Vite 代理；本地代理用 M3 dev 默认端口/令牌）。
 *
 * 灰度策略：`orchestration` 决定 deploy/push/pull/import 等是否走「云端产物 → 本地代理落盘 →
 * 云端登记」的多步编排链。web 灰度默认 **false**（沿用旧的一次性云端端点，不依赖本地代理，
 * 保证现有 web 形态可用）；桌面形态（M5 注入 mode='desktop'）默认 **true**。
 */

export type AppMode = 'web' | 'desktop'

export interface VibebaraRuntimeConfig {
  /** 运行形态：web 灰度 / desktop 桌面壳。 */
  mode: AppMode
  /** 桌面主进程注入的可信操作系统；web 形态下不设置。 */
  platform?: 'win32' | 'darwin' | 'linux'
  /** 云端 REST API 基址，axios baseURL。web 默认 `/api/v1`（经 Vite/反代）。 */
  cloudApiBase: string
  /**
   * 云端 WebSocket 基址（不含路径），如 `wss://api.vibebara.example`。
   * 为空字符串时回退到 `window.location`（dev/同源部署兼容）。
   */
  cloudWsBase: string
  /** 本地代理基址，如 `http://127.0.0.1:51873`。 */
  localAgentBase: string
  /** 本地代理端口（与 localAgentBase 二选一注入；用于回推 base）。 */
  localAgentPort: number
  /** 本地配对令牌（X-Pairing-Token）。M5 由桌面主进程注入；dev 用 M3 固定令牌。 */
  pairingToken: string
  /**
   * 是否启用「前端编排」多步链路（云端产物 → 本地代理落盘 → 云端登记）。
   * false = 走旧的一次性云端端点（web 灰度回退，不触达本地代理）。
   */
  orchestration: boolean
  /**
   * 有效设备标识（M5-b）。桌面壳注入 = `registeredDeviceId ?? clientUuid`：
   * 登录注册前为本机 `clientUuid` 占位，注册后即为云端铸造的规范 `device_id`。
   * 前端正式形态用它做平台安装态上报维度键。web 形态下为 undefined。
   */
  deviceId?: string
  /**
   * 本机持久 uuid（M5-b 桌面壳注入）。设备注册（POST /devices/register）的幂等键，
   * **非鉴权凭证**。web 形态下为 undefined（前端据此安全跳过注册）。
   */
  clientUuid?: string
}

// —— M3 本地代理 dev 默认（见 local-agent/src/constants.ts）——
const DEV_LOCAL_AGENT_PORT = 51873
const DEV_PAIRING_TOKEN = 'vibebara-dev-insecure-pairing-token-change-me'

const DEFAULTS: VibebaraRuntimeConfig = {
  mode: 'web',
  cloudApiBase: '/api/v1',
  cloudWsBase: '',
  localAgentBase: `http://127.0.0.1:${DEV_LOCAL_AGENT_PORT}`,
  localAgentPort: DEV_LOCAL_AGENT_PORT,
  pairingToken: DEV_PAIRING_TOKEN,
  orchestration: false,
}

declare global {
  interface Window {
    /** M5 桌面壳注入的运行时配置（preload/contextBridge）。 */
    __VIBEBARA_RUNTIME__?: Partial<VibebaraRuntimeConfig>
  }
}

function readInjected(): Partial<VibebaraRuntimeConfig> {
  if (typeof window !== 'undefined' && window.__VIBEBARA_RUNTIME__) {
    return window.__VIBEBARA_RUNTIME__
  }
  return {}
}

function readEnv(): Partial<VibebaraRuntimeConfig> {
  const env = import.meta.env as Record<string, string | undefined>
  const out: Partial<VibebaraRuntimeConfig> = {}
  if (env.VITE_CLOUD_API_BASE) out.cloudApiBase = env.VITE_CLOUD_API_BASE
  if (env.VITE_CLOUD_WS_BASE) out.cloudWsBase = env.VITE_CLOUD_WS_BASE
  if (env.VITE_LOCAL_AGENT_BASE) out.localAgentBase = env.VITE_LOCAL_AGENT_BASE
  if (env.VITE_LOCAL_AGENT_PORT) {
    const p = Number(env.VITE_LOCAL_AGENT_PORT)
    if (Number.isFinite(p) && p > 0) out.localAgentPort = p
  }
  if (env.VITE_PAIRING_TOKEN) out.pairingToken = env.VITE_PAIRING_TOKEN
  if (env.VITE_APP_MODE === 'web' || env.VITE_APP_MODE === 'desktop') {
    out.mode = env.VITE_APP_MODE
  }
  if (env.VITE_ORCHESTRATION != null) {
    out.orchestration = env.VITE_ORCHESTRATION === 'true'
  }
  return out
}

let cached: VibebaraRuntimeConfig | null = null

/**
 * 解析并缓存运行时配置。合并优先级：默认 < env < window 注入。
 * 派生规则：
 *   - 若只注入了 localAgentPort 未注入 base，则按端口重算 localAgentBase；
 *   - orchestration 未显式设置时，按 mode 推断（desktop → true）。
 */
export function getRuntimeConfig(): VibebaraRuntimeConfig {
  if (cached) return cached

  const env = readEnv()
  const injected = readInjected()
  const merged: VibebaraRuntimeConfig = { ...DEFAULTS, ...env, ...injected }

  // 端口注入但未给 base 时，按端口回推本地代理 base
  const baseExplicit =
    env.localAgentBase != null || injected.localAgentBase != null
  const portExplicit =
    env.localAgentPort != null || injected.localAgentPort != null
  if (!baseExplicit && portExplicit) {
    merged.localAgentBase = `http://127.0.0.1:${merged.localAgentPort}`
  }

  // orchestration 未显式设置时按 mode 推断
  const orchestrationExplicit =
    env.orchestration != null || injected.orchestration != null
  if (!orchestrationExplicit) {
    merged.orchestration = merged.mode === 'desktop'
  }

  cached = merged
  return merged
}

/** 是否启用前端多步编排链路（否则走旧的一次性云端端点）。 */
export function isOrchestrationEnabled(): boolean {
  return getRuntimeConfig().orchestration
}

/** 当前配对令牌（发给本地代理）。 */
export function getPairingToken(): string {
  return getRuntimeConfig().pairingToken
}

/** 有效设备标识（M5-b）：registeredDeviceId ?? clientUuid；web 形态下为空串。 */
export function getDeviceId(): string {
  return getRuntimeConfig().deviceId ?? ''
}

/** 本机持久 uuid（M5-b 设备注册幂等键）；web 形态下为空串（前端据此跳过注册）。 */
export function getClientUuid(): string {
  return getRuntimeConfig().clientUuid ?? ''
}

/**
 * 注册成功后更新有效 deviceId（M5-b 任务①）。
 * 桌面壳已经桥回写 vibebara-device.json；此处同步前端缓存，使后续上报用规范 device_id。
 */
export function setDeviceId(deviceId: string): void {
  const cfg = getRuntimeConfig()
  if (deviceId && deviceId.trim()) {
    cfg.deviceId = deviceId.trim()
  }
}

/**
 * 热更本地代理基址（M5-b 任务②：端口漂移）。
 * 桌面壳本地代理崩溃重启分到新端口时，经 IPC 推送→此处更新缓存，
 * localAgentClient 每次请求动态读取 base，使端口漂移对用户透明。web 形态不触发。
 */
export function updateLocalAgentBase(base: string, port?: number): void {
  const cfg = getRuntimeConfig()
  if (base && base.trim()) {
    cfg.localAgentBase = base.trim()
  }
  if (typeof port === 'number' && Number.isFinite(port) && port > 0) {
    cfg.localAgentPort = port
  }
}

/** 当前本地代理基址（localAgentClient 每次请求动态读取，端口漂移透明）。 */
export function getLocalAgentBase(): string {
  return getRuntimeConfig().localAgentBase
}

/**
 * 拼接云端 WebSocket 完整 URL。
 * - 配了 cloudWsBase（如 `wss://api.example`）：直接拼路径；
 * - 未配置（web/同源 dev）：回退到 `window.location` 推导 ws/wss。
 * @param path 以 `/` 开头的 WS 路径，如 `/ws/project/123`
 */
export function cloudWsUrl(path: string): string {
  const cfg = getRuntimeConfig()
  if (cfg.cloudWsBase) {
    return cfg.cloudWsBase.replace(/\/+$/, '') + path
  }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}