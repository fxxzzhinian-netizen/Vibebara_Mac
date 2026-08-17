import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  register,
  login,
  getMe,
  saveOnboarding,
  updateProfile,
  uploadAvatar,
  deleteAvatar,
  type UserInfo,
  type UpdateProfilePayload,
} from '@/api/auth'
import { ensureDeviceRegistered } from '@/api/devices'
import { getToken, setToken, removeToken } from '@/runtime/tokenStorage'
import { DEV_SKIP_AUTH, DEV_FAKE_USER } from '@/runtime/devAuth'

export const useAuthStore = defineStore('auth', () => {
  const token = ref(getToken())
  // 开发者模式：预置假用户，使 isLoggedIn 成立且不被引导页拦截。
  const user = ref<UserInfo | null>(DEV_SKIP_AUTH ? DEV_FAKE_USER : null)
  const loading = ref(false)
  const error = ref('')

  const isLoggedIn = computed(() => !!token.value && !!user.value)

  async function doRegister(
    username: string,
    password: string,
    inviteCode: string,
    captchaToken: string,
    displayName?: string,
  ) {
    loading.value = true
    error.value = ''
    try {
      const res = await register(
        username,
        password,
        inviteCode,
        captchaToken,
        displayName,
      )
      if (res.success) {
        token.value = res.token
        setToken(res.token)
        await fetchMe()
        // M5-b：桌面形态下登录成功后注册设备身份（web 形态安全跳过）。
        void ensureDeviceRegistered()
      } else {
        error.value = res.error || '注册失败'
      }
      return res
    } catch (e: any) {
      console.error('[auth] 注册请求失败 POST /auth/register:', e)
      error.value = e?.response?.data?.detail || e.message
      return { success: false, error: error.value } as any
    } finally {
      loading.value = false
    }
  }

  async function doLogin(
    username: string,
    password: string,
    captchaToken: string,
  ) {
    loading.value = true
    error.value = ''
    try {
      const res = await login(username, password, captchaToken)
      if (res.success) {
        token.value = res.token
        setToken(res.token)
        await fetchMe()
        // M5-b：桌面形态下登录成功后注册设备身份（web 形态安全跳过）。
        void ensureDeviceRegistered()
      } else {
        error.value = res.error || '登录失败'
      }
      return res
    } catch (e: any) {
      console.error('[auth] 登录请求失败 POST /auth/login:', e)
      error.value = e?.response?.data?.detail || e.message
      return { success: false, error: error.value } as any
    } finally {
      loading.value = false
    }
  }

  async function fetchMe() {
    // 开发者模式：不打后端，直接维持假用户（避免 401 触发 logout 清登录态）。
    if (DEV_SKIP_AUTH) {
      user.value = DEV_FAKE_USER
      return
    }
    if (!token.value) return
    try {
      const res = await getMe()
      if (res.success && res.user) {
        user.value = res.user
      }
    } catch (e) {
      console.error('[auth] 获取当前用户失败（将清除本地登录态）GET /auth/me:', e)
      logout()
    }
  }

  async function completeOnboarding(devMode: string, favoriteTool: string) {
    // 开发者模式：不打后端（假 token 会 401），本地置 onboarded=true 让引导页能正常收尾进入工作台。
    if (DEV_SKIP_AUTH) {
      user.value = {
        ...(user.value ?? DEV_FAKE_USER),
        onboarded: true,
        dev_mode: devMode,
        favorite_tool: favoriteTool,
      }
      return { success: true }
    }
    try {
      const res = await saveOnboarding(devMode, favoriteTool)
      if (res.success && user.value) {
        user.value = {
          ...user.value,
          onboarded: true,
          dev_mode: devMode,
          favorite_tool: favoriteTool,
        }
      }
      return res
    } catch (e: any) {
      console.error('[auth] 保存引导选择失败 POST /auth/onboarding:', e)
      return {
        success: false,
        error: e?.response?.data?.detail || e.message,
      }
    }
  }

  async function saveProfile(payload: UpdateProfilePayload) {
    if (DEV_SKIP_AUTH) {
      user.value = {
        ...(user.value ?? DEV_FAKE_USER),
        ...payload,
      }
      return { success: true, user: user.value }
    }
    try {
      const res = await updateProfile(payload)
      if (res.success && res.user) user.value = res.user
      return res
    } catch (e: any) {
      return {
        success: false,
        error: e?.response?.data?.detail || e?.response?.data?.error || e.message,
      }
    }
  }

  async function saveAvatar(file: File) {
    if (DEV_SKIP_AUTH) {
      const previewUrl = URL.createObjectURL(file)
      user.value = {
        ...(user.value ?? DEV_FAKE_USER),
        avatar_url: previewUrl,
      }
      return { success: true, user: user.value }
    }
    try {
      const res = await uploadAvatar(file)
      if (res.success && res.user) user.value = res.user
      return res
    } catch (e: any) {
      return {
        success: false,
        error: e?.response?.data?.detail || e?.response?.data?.error || e.message,
      }
    }
  }

  async function removeAvatar() {
    if (DEV_SKIP_AUTH) {
      user.value = {
        ...(user.value ?? DEV_FAKE_USER),
        avatar_url: null,
      }
      return { success: true, user: user.value }
    }
    try {
      const res = await deleteAvatar()
      if (res.success && res.user) user.value = res.user
      return res
    } catch (e: any) {
      return {
        success: false,
        error: e?.response?.data?.detail || e?.response?.data?.error || e.message,
      }
    }
  }

  function logout() {
    token.value = ''
    user.value = null
    removeToken()
  }

  async function init() {
    // 开发者模式：跳过会话恢复（fetchMe）与设备注册，直接以假用户进入。
    if (DEV_SKIP_AUTH) {
      user.value = DEV_FAKE_USER
      return
    }
    if (token.value) {
      await fetchMe()
      // M5-b：已登录会话恢复时也确保设备已注册（幂等，桌面形态有效）。
      if (user.value) {
        void ensureDeviceRegistered()
      }
    }
  }

  return {
    token,
    user,
    loading,
    error,
    isLoggedIn,
    doRegister,
    doLogin,
    fetchMe,
    completeOnboarding,
    saveProfile,
    saveAvatar,
    removeAvatar,
    logout,
    init,
  }
})
