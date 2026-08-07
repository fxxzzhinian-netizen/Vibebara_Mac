import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { ChangeItem } from '@/api/projects'

export interface NotificationMessage {
  id: string
  skill_id: string
  deployment_id?: string | null
  user_id: string
  user_display_name: string
  skill_display_name: string
  source?: string
  action: string
  version?: number
  timestamp: string
  change_items?: ChangeItem[]
  diff_summary?: string
}

const ACTION_LABELS: Record<string, string> = {
  created: '创建了',
  updated: '修改了',
  deleted: '删除了',
  deployed: '部署了',
  pushed: '推送了',
  pulled: '更新了本地',
  merged: 'AI 合并提交了',
  conflict: '推送冲突',
  linked: '关联了',
  unlinked: '移除了',
  resumed: '恢复了跟踪',
  stopped: '停止了跟踪',
  missing: '检测到部署路径缺失',
  promoted: '提交了部署内容',
  auto_promoted: '自动同步了部署内容',
}

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] || '操作了'
}

export function formatNotification(msg: NotificationMessage): string {
  const verb = actionLabel(msg.action)
  const base = `${msg.user_display_name} ${verb} ${msg.skill_display_name}`
  if (msg.diff_summary && msg.diff_summary !== '无改动') {
    return `${base}：${msg.diff_summary}`
  }
  return base
}

const MAX_MESSAGES = 50

export const useNotificationStore = defineStore('notification', () => {
  const messages = ref<NotificationMessage[]>([])

  /**
   * 记录一条「项目动态」历史（只入历史列表）。
   * 实时浮窗已统一改走全局提示窗（AppToast）：他人改动由 useSkillSync 调一次
   * toast 提示，自己的操作由本地成功提示给出，不再使用独立的浮窗队列。
   */
  function addMessage(msg: NotificationMessage) {
    messages.value.unshift(msg)
    if (messages.value.length > MAX_MESSAGES) {
      messages.value = messages.value.slice(0, MAX_MESSAGES)
    }
  }

  function loadHistory(items: NotificationMessage[]) {
    messages.value = items.slice(0, MAX_MESSAGES)
  }

  function clear() {
    messages.value = []
  }

  return {
    messages,
    addMessage,
    loadHistory,
    clear,
  }
})
