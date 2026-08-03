export interface RelativeTimeOptions {
  emptyText?: string
  relativeDayLimit?: number
  now?: number
}

/**
 * 后端的 DateTime 字段按 UTC 写入，但部分数据库会在读取时丢失时区后缀。
 * 对没有 Z / UTC 偏移的日期时间补上 Z，避免浏览器误按本地时间解析。
 */
export function parseServerDateTime(value: string | null | undefined): Date | null {
  const raw = value?.trim()
  if (!raw) return null

  const hasTime = /[T ]\d{2}:\d{2}/.test(raw)
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw)
  const normalized = hasTime && !hasTimezone
    ? `${raw.replace(' ', 'T')}Z`
    : raw
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatRelativeTime(
  value: string | null | undefined,
  options: RelativeTimeOptions = {},
): string {
  const {
    emptyText = '',
    relativeDayLimit = 1,
    now = Date.now(),
  } = options
  const date = parseServerDateTime(value)
  if (!date) return emptyText

  // 服务端与客户端时钟有轻微偏差时，不展示负数时间。
  const diff = Math.max(0, now - date.getTime())
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`

  const days = Math.floor(diff / 86_400_000)
  if (days < relativeDayLimit) return `${days} 天前`
  return date.toLocaleDateString('zh-CN')
}
