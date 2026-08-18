import { ref, onUnmounted, watch } from 'vue'
import { useProjectSyncStore } from '@/stores/projectSyncStore'
import { useSkillStore } from '@/stores/skillStore'
import { useNotificationStore, formatNotification } from '@/stores/notificationStore'
import { useAuthStore } from '@/stores/authStore'
import { toast } from '@/composables/useToast'
import { cloudWsUrl } from '@/runtime/config'
import { getToken } from '@/runtime/tokenStorage'
import type { ChangeItem } from '@/api/projects'

export interface SkillSyncEvent {
  type: string
  project_id: string
  skill_id: string
  deployment_id?: string | null
  version: number
  content_hash: string
  user_id: string
  user_display_name: string
  skill_display_name: string
  source?: string
  timestamp: string
  change_items?: ChangeItem[]
  diff_summary?: string
  status?: string
}

/**
 * 项目级 Skill 实时同步 composable。
 *
 * 连接到 ws://host/ws/project/{projectId}，
 * 收到 skill.* 事件后自动通知 store 并按需拉取最新内容。
 */
export function useSkillSync(
  projectId: () => string | null,
  onSkillEvent?: (evt: SkillSyncEvent) => void | Promise<void>,
) {
  const connected = ref(false)
  const events = ref<SkillSyncEvent[]>([])
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let manualClose = false

  const projectSyncStore = useProjectSyncStore()
  const skillStore = useSkillStore()
  const notificationStore = useNotificationStore()
  const authStore = useAuthStore()

  function closeSocket() {
    if (ws) {
      // 拆掉旧 socket 的回调，避免它触发自动重连
      ws.onopen = null
      ws.onmessage = null
      ws.onclose = null
      ws.onerror = null
      try {
        ws.close()
      } catch {
        // ignore
      }
      ws = null
    }
  }

  function connect(pid: string, userId: string) {
    manualClose = false
    closeSocket()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = undefined
    }

    const token = getToken()
    if (!token) {
      connected.value = false
      return
    }
    // WS 云端化（M0 §9）：用 runtimeConfig 的云端 WS 基址；未配置时回退当前 host（dev/同源兼容）。
    const url =
      cloudWsUrl(`/ws/project/${pid}`) +
      `?user_id=${encodeURIComponent(userId)}&token=${encodeURIComponent(token)}`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
    }

    ws.onmessage = (e) => {
      try {
        const evt: SkillSyncEvent = JSON.parse(e.data)
        events.value.push(evt)
        handleEvent(evt)
      } catch {
        // ignore malformed
      }
    }

    ws.onclose = (event) => {
      connected.value = false
      if (event.code === 4001) {
        manualClose = true
        window.dispatchEvent(
          new CustomEvent('vibebara:unauthorized', {
            detail: { reason: '账号已在另一台设备登录' },
          }),
        )
        return
      }
      // 非主动关闭（断线/服务端重启）时定时重连，保证动态实时性
      if (
        !manualClose &&
        projectId() === pid &&
        authStore.user?.id === userId
      ) {
        reconnectTimer = setTimeout(() => connect(pid, userId), 3000)
      }
    }

    ws.onerror = () => {
      connected.value = false
    }
  }

  async function handleEvent(evt: SkillSyncEvent) {
    projectSyncStore.handleSkillEvent(evt)

    if (evt.user_display_name && evt.type.startsWith('skill.')) {
      const msg = {
        id: `${evt.skill_id}-${evt.timestamp}-${Math.random().toString(36).slice(2, 8)}`,
        skill_id: evt.skill_id,
        deployment_id: evt.deployment_id,
        user_id: evt.user_id,
        user_display_name: evt.user_display_name,
        skill_display_name: evt.skill_display_name || evt.skill_id,
        source: evt.source,
        action: evt.type.replace('skill.', ''),
        version: evt.version,
        timestamp: evt.timestamp,
        change_items: evt.change_items,
        diff_summary: evt.diff_summary,
      }
      // 始终记入「项目动态」历史。
      notificationStore.addMessage(msg)
      // 提示统一走全局提示窗（AppToast），且每个事件只弹一次：
      //   - 自己触发的事件不再弹（成功已由本地操作的全局提示给出一次），避免与服务端广播叠加；
      //   - 他人的改动（如别人推送）弹一次全局提示窗。
      const selfId = authStore.user?.id || ''
      const isSelf = !!evt.user_id && evt.user_id === selfId
      if (!isSelf) {
        toast.info(formatNotification(msg), undefined, '团队动态')
      }
    }

    if (
      (evt.type === 'skill.pushed' || evt.type === 'skill.pulled') &&
      evt.project_id === projectSyncStore.currentProjectId
    ) {
      await projectSyncStore.selectProject(evt.project_id)
    }

    if (
      evt.type === 'skill.updated' ||
      evt.type === 'skill.created' ||
      evt.type === 'skill.deployed'
    ) {
      if (skillStore.currentId === evt.skill_id) {
        await skillStore.selectSkill(evt.skill_id)
      }
      await skillStore.fetchList()
    }

    if (evt.type === 'skill.deleted') {
      if (skillStore.currentId === evt.skill_id) {
        skillStore.clearCurrent()
      }
      await skillStore.fetchList()
    }

    // 任意 skill.* 事件后，让订阅方重新拉取权威动态历史（保证改动点准确实时）
    if (onSkillEvent && evt.type.startsWith('skill.')) {
      await onSkillEvent(evt)
    }
  }

  function disconnect() {
    manualClose = true
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = undefined
    }
    closeSocket()
    connected.value = false
  }

  const stopWatch = watch(
    [projectId, () => authStore.user?.id ?? null],
    ([newId, userId]) => {
      if (newId && userId) {
        connect(newId, userId)
      } else {
        disconnect()
      }
    },
    { immediate: true },
  )

  onUnmounted(() => {
    stopWatch()
    disconnect()
  })

  return { connected, events, disconnect }
}
