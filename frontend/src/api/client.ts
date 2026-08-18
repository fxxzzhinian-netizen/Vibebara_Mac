import axios from 'axios'
import {
  getRuntimeConfig,
  getPairingToken,
  getLocalAgentBase,
  updateLocalAgentBase,
} from '@/runtime/config'
import { getToken } from '@/runtime/tokenStorage'
import { getDesktopBridge } from '@/runtime/desktopBridge'

/**
 * 双 client 分离（M4 前端分流，见 M0 §9 / §5.2）：
 *
 *   - cloudClient：发往云端 FastAPI（`/api/v1`）。携带 `Authorization: Bearer <token>`
 *     （云端身份）。**绝不**携带配对令牌。
 *   - localAgentClient：发往本地代理（`http://127.0.0.1:PORT`）。携带
 *     `X-Pairing-Token: <pairingToken>`（本机设备配对）。**绝不**携带 Bearer。
 *
 * 两套地址/令牌由 runtimeConfig 提供：web 灰度用安全默认（云端 `/api/v1` + Vite 代理、
 * 本地代理用 M3 dev 端口/令牌）；M5 桌面壳通过 window.__VIBEBARA_RUNTIME__ 注入真实值。
 */

const runtime = getRuntimeConfig()

// ===== 云端 client（Bearer Token → 云端 API 基址）=====
// timeout：云端不可达/被代理或防火墙挂起时，让请求按时失败抛错（拦截器/调用方可展示
// “连接失败”），避免无超时导致登录按钮卡在“登录中…”、首屏白屏等“无报错却进不去”的表现。
export const cloudClient = axios.create({
  baseURL: runtime.cloudApiBase,
  timeout: 15000,
  headers: {
    'Content-Type': 'application/json',
  },
})

/**
 * GET 防缓存：给 GET 请求附唯一查询参数，使每次 URL 不同、强制走网络。
 *
 * 背景：Electron/Chromium 会缓存 GET 响应。曾出现链路异常（如 VPN 残留代理）时
 * 接口返回 403/401，被浏览器缓存住；链路恢复后相同 URL 仍命中缓存的旧失败响应，
 * 请求根本不再发出，表现为“验证码加载失败 / 登录后 /auth/me 403”等顽固故障。
 * 这些接口（验证码挑战、当前用户、列表等）本就应取实时数据，禁用缓存无副作用。
 */
function applyNoCache(config: { method?: string; params?: any }) {
  if ((config.method ?? 'get').toLowerCase() === 'get') {
    config.params = { ...(config.params ?? {}), _t: Date.now() }
  }
}

cloudClient.interceptors.request.use((config) => {
  // 按形态取 token：桌面=safeStorage（经桥同步缓存），web=localStorage。
  const token = getToken()
  if (token && config.headers) {
    config.headers.Authorization = `Bearer ${token}`
  }
  applyNoCache(config)
  return config
})

// ===== 本地代理 client（X-Pairing-Token → 127.0.0.1:PORT）=====
// baseURL 不在创建时写死：M5-b 任务② 本地代理崩溃重启可能漂移到新端口，
// 故每次请求动态读取 runtimeConfig.localAgentBase，使端口漂移对用户透明。
export const localAgentClient = axios.create({
  baseURL: runtime.localAgentBase, // 初始值；下方拦截器每次请求按最新 base 覆盖
  headers: {
    'Content-Type': 'application/json',
  },
})

localAgentClient.interceptors.request.use((config) => {
  // 动态读取本地代理 base（端口漂移热更后即时生效）。
  config.baseURL = getLocalAgentBase()
  // 配对令牌每次实时读取（M5 桌面壳可能在运行中轮换 pairingSecret）
  if (config.headers) {
    config.headers['X-Pairing-Token'] = getPairingToken()
  }
  applyNoCache(config)
  return config
})

// ===== 统一请求错误日志 =====
// 排查“加载失败但无报错”类问题：把失败的接口请求打到控制台，并区分三类：
//   1. 有响应：打印 HTTP 状态码 + 后端返回体（如 401/422/500）；
//   2. 无响应：网络不可达 / 超时 / 被系统代理拦截（如 VPN 残留代理 127.0.0.1:port）；
//   3. 请求构造阶段错误。
// 仅记录日志，不吞错：继续 reject，调用方原有逻辑完全不变。
function logApiError(scope: 'cloud' | 'local', error: any) {
  const cfg = error?.config ?? {}
  const method = String(cfg.method ?? 'GET').toUpperCase()
  const url = `${cfg.baseURL ?? ''}${cfg.url ?? ''}`
  const res = error?.response
  if (res) {
    console.error(
      `[api:${scope}] ${method} ${url} → HTTP ${res.status} ${res.statusText ?? ''}`,
      res.data,
    )
  } else if (error?.request) {
    console.error(
      `[api:${scope}] ${method} ${url} → 无响应（网络不可达/超时/被代理拦截） code=${error.code ?? '?'} msg=${error.message ?? ''}`,
    )
  } else {
    console.error(`[api:${scope}] 请求构造失败: ${error?.message ?? error}`)
  }
  return Promise.reject(error)
}

cloudClient.interceptors.response.use((r) => r, (e) => {
  const status = e?.response?.status
  const url = String(e?.config?.url ?? '')
  const isLoginRequest = url.includes('/auth/login') || url.includes('/auth/register')
  if (status === 401 && !isLoginRequest && typeof window !== 'undefined') {
    const detail = e?.response?.data?.detail
    window.dispatchEvent(
      new CustomEvent('vibebara:unauthorized', {
        detail: {
          reason: typeof detail === 'string' ? detail : '登录状态已失效，请重新登录',
        },
      }),
    )
  }
  return logApiError('cloud', e)
})
localAgentClient.interceptors.response.use((r) => r, (e) => logApiError('local', e))

// 桌面形态：订阅本地代理端口漂移热更（任务②）。web 形态桥不存在 → 跳过，行为不变。
const _desktopBridge = getDesktopBridge()
if (_desktopBridge?.onLocalAgentChange) {
  _desktopBridge.onLocalAgentChange((payload) => {
    updateLocalAgentBase(payload.localAgentBase, payload.localAgentPort)
  })
}

/**
 * 兼容旧代码：默认导出 = 云端 client。
 * 历史上各 api/*.ts 以 `import apiClient from './client'` 调用云端，保持不变。
 */
const apiClient = cloudClient
export default apiClient
