import { getClientUuid } from './config'
import { isDesktop } from './desktopBridge'

const WEB_CLIENT_UUID_KEY = 'vibebara_web_client_uuid'

function randomUuid(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return `web-${Date.now()}-${Math.random().toString(36).slice(2)}`
}

export function getLoginClientUuid(): string {
  const desktopUuid = getClientUuid()
  if (isDesktop() && desktopUuid) return desktopUuid
  let value = localStorage.getItem(WEB_CLIENT_UUID_KEY) || ''
  if (!value) {
    value = randomUuid()
    localStorage.setItem(WEB_CLIENT_UUID_KEY, value)
  }
  return value
}

export function guessClientPlatform(): string {
  if (typeof navigator === 'undefined') return ''
  const ua = (navigator.userAgent || '').toLowerCase()
  if (ua.includes('win')) return 'win32'
  if (ua.includes('mac')) return 'darwin'
  if (ua.includes('linux')) return 'linux'
  return 'web'
}

export function getLoginDeviceMetadata() {
  return {
    client_uuid: getLoginClientUuid(),
    platform: guessClientPlatform(),
  }
}
