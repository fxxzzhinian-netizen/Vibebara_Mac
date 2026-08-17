import apiClient from './client'
import { getRuntimeConfig } from '@/runtime/config'

export interface TokenResponse {
  success: boolean
  token: string
  user_id: string
  username: string
  error?: string
}

export interface UserInfo {
  id: string
  username: string
  display_name: string
  email: string | null
  avatar_url: string | null
  phone: string | null
  gender: string | null
  birthday: string | null
  locale: string | null
  location: string | null
  created_at: string | null
  onboarded: boolean
  dev_mode: string | null
  favorite_tool: string | null
  // SKILL 市场权限标记（后端 /auth/me 下发；前端据此显示审核 / 管理员入口）
  is_platform_admin?: boolean
  is_seed_user?: boolean
  is_reviewer?: boolean
  can_manage_admins?: boolean
}

export interface OnboardingResponse {
  success: boolean
  error?: string
}

export interface GenerateApiKeyResponse {
  success: boolean
  api_key: string
  error?: string
}

export interface ApiKeyStatusResponse {
  success: boolean
  has_api_key: boolean
}

export interface UserResponse {
  success: boolean
  user?: UserInfo
  error?: string
}

export interface UpdateProfilePayload {
  display_name?: string
  email?: string | null
  phone?: string | null
  gender?: string | null
  birthday?: string | null
  locale?: string | null
  location?: string | null
}

export interface CaptchaChallenge {
  success: boolean
  captcha_id: string
  bg: string
  piece: string
  piece_y: number
  bg_width: number
  bg_height: number
  piece_width: number
  piece_height: number
  error?: string
}

export interface CaptchaVerifyResponse {
  success: boolean
  captcha_token: string
  error?: string
}

export async function getCaptcha(): Promise<CaptchaChallenge> {
  // 防缓存由 client.ts 的请求拦截器对所有 GET 统一处理（附唯一 _t 参数）。
  const { data } = await apiClient.get<CaptchaChallenge>('/auth/captcha')
  return data
}

export async function verifyCaptcha(
  captchaId: string,
  x: number,
): Promise<CaptchaVerifyResponse> {
  const { data } = await apiClient.post<CaptchaVerifyResponse>(
    '/auth/captcha/verify',
    { captcha_id: captchaId, x },
  )
  return data
}

export async function register(
  username: string,
  password: string,
  inviteCode: string,
  captchaToken: string,
  display_name?: string,
  email?: string,
): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/register', {
    username,
    password,
    invite_code: inviteCode,
    captcha_token: captchaToken,
    display_name: display_name ?? '',
    email: email ?? null,
  })
  return data
}

export async function login(
  username: string,
  password: string,
  captchaToken: string,
): Promise<TokenResponse> {
  const { data } = await apiClient.post<TokenResponse>('/auth/login', {
    username,
    password,
    captcha_token: captchaToken,
  })
  return data
}

export async function getMe(): Promise<UserResponse> {
  const { data } = await apiClient.get<UserResponse>('/auth/me')
  return data
}

export async function updateProfile(
  payload: UpdateProfilePayload,
): Promise<UserResponse> {
  const { data } = await apiClient.patch<UserResponse>('/auth/me', payload)
  return data
}

export async function uploadAvatar(file: File): Promise<UserResponse> {
  const form = new FormData()
  form.append('file', file)
  const { data } = await apiClient.post<UserResponse>('/auth/me/avatar', form, {
    // 清除 client 的 JSON 默认值，让浏览器为 FormData 自动生成 multipart boundary。
    headers: { 'Content-Type': undefined },
    timeout: 30000,
  })
  return data
}

export async function deleteAvatar(): Promise<UserResponse> {
  const { data } = await apiClient.delete<UserResponse>('/auth/me/avatar')
  return data
}

/** 将后端返回的 API 相对路径解析为 web/Electron 均可加载的头像地址。 */
export function resolveAvatarUrl(url: string | null | undefined): string {
  if (!url) return ''
  if (/^(https?:|data:|blob:)/i.test(url)) return url

  const apiBase = getRuntimeConfig().cloudApiBase.replace(/\/+$/, '')
  const absolutePath = `/${url.replace(/^\/+/, '')}`

  // 后端当前返回从站点根开始的 /api/v1/...；避免与 apiBase 中已有的
  // /api/v1 再次拼接。桌面端 apiBase 为绝对 URL，需要保留其 origin。
  if (absolutePath.startsWith('/api/')) {
    if (/^https?:\/\//i.test(apiBase)) {
      return new URL(absolutePath, apiBase).toString()
    }
    return absolutePath
  }

  return `${apiBase}${absolutePath}`
}

export async function generateApiKey(): Promise<GenerateApiKeyResponse> {
  const { data } = await apiClient.post<GenerateApiKeyResponse>('/auth/api-key')
  return data
}

export async function getApiKeyStatus(): Promise<ApiKeyStatusResponse> {
  const { data } = await apiClient.get<ApiKeyStatusResponse>('/auth/api-key/status')
  return data
}

export async function saveOnboarding(
  devMode: string,
  favoriteTool: string,
): Promise<OnboardingResponse> {
  const { data } = await apiClient.post<OnboardingResponse>('/auth/onboarding', {
    dev_mode: devMode,
    favorite_tool: favoriteTool,
  })
  return data
}
