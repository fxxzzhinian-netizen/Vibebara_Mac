/**
 * 设备身份 client（方案 B · M5-b 设备身份地基，契约 §4.2.1）。
 *
 * 登录成功后，桌面形态下前端持 Bearer 调 `POST /devices/register {clientUuid,...}`：
 *   · 云端按 (user, clientUuid) 幂等 upsert、**服务端铸造** device_id 并返回；
 *   · 前端经桌面桥 persistDeviceId 把规范 device_id 回写 vibebara-device.json，
 *     并 setDeviceId 更新前端运行时缓存（后续平台安装态上报用规范 device_id）。
 *
 * 灰度安全：web 形态无 clientUuid（runtime.clientUuid 为空）→ 安全跳过（不注册、不报错）。
 * device_id 非鉴权凭证；云端以 Bearer 为身份并按归属校验（设计 §3.4 / §8）。
 */
import { cloudClient } from './client'
import { getClientUuid, setDeviceId } from '@/runtime/config'
import { getDesktopBridge, isDesktop } from '@/runtime/desktopBridge'
import { guessClientPlatform } from '@/runtime/deviceIdentity'

// ===================== DTO（契约 §4.2.1，camelCase）=====================

export interface DeviceInfo {
  deviceId: string
  clientUuid: string
  platform: string
  hostname?: string
  appVersion?: string
  agentVersion?: string
  status: 'active' | 'revoked'
  lastSeenAt: string | null
  lastSyncAt: string | null
  createdAt: string | null
}

export interface DeviceRegisterRequest {
  clientUuid: string
  platform?: string
  hostname?: string
  appVersion?: string
  agentVersion?: string
}

export interface DeviceRegisterResponse {
  success: boolean
  device?: DeviceInfo
  error?: string
}

// ===================== 端点调用 =====================

/** POST /devices/register —— 注册/刷新设备（幂等：(user, clientUuid)）。 */
export async function registerDevice(
  body: DeviceRegisterRequest,
): Promise<DeviceRegisterResponse> {
  const { data } = await cloudClient.post<DeviceRegisterResponse>(
    '/devices/register',
    body,
  )
  return data
}

export async function acceptLoginDeviceId(deviceId: string): Promise<void> {
  if (!deviceId) return
  const bridge = getDesktopBridge()
  if (bridge?.persistDeviceId) {
    await bridge.persistDeviceId(deviceId)
  }
  setDeviceId(deviceId)
}

/**
 * 登录后设备注册编排（M5-b 任务①）。
 *
 * 桌面形态 + 有 clientUuid 时：注册 → 拿 device_id → 桥回写本机 + 更新前端运行时。
 * web 形态 / 无 clientUuid：安全跳过（返回 null，不报错、不影响登录）。
 * 任何失败仅告警、不抛出（注册非登录硬依赖；可由后续触发重试）。
 */
export async function ensureDeviceRegistered(): Promise<string | null> {
  const clientUuid = getClientUuid()
  if (!isDesktop() || !clientUuid) {
    return null // web 形态或无 clientUuid → 安全跳过
  }
  try {
    const res = await registerDevice({
      clientUuid,
      platform: guessClientPlatform() || undefined,
    })
    if (!res.success || !res.device) {
      console.warn('[devices] 注册未成功:', res.error)
      return null
    }
    const deviceId = res.device.deviceId
    // 经桥回写本机 vibebara-device.json.registeredDeviceId（主进程同时热更运行时）。
    try {
      await acceptLoginDeviceId(deviceId)
    } catch (e) {
      console.warn('[devices] 回写 device_id 到桌面失败:', (e as Error)?.message)
    }
    return deviceId
  } catch (e) {
    console.warn('[devices] 设备注册失败（不影响登录，可后续重试）:', (e as Error)?.message)
    return null
  }
}
