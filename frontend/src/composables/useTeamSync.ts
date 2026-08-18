import { ref, onUnmounted, watch } from 'vue'
import { cloudWsUrl } from '@/runtime/config'
import { getToken } from '@/runtime/tokenStorage'
import { useAuthStore } from '@/stores/authStore'

export interface TeamSyncEvent {
  type: string
  team_id: string
  user_id: string
  user_display_name?: string
  project_id?: string
  skill_id?: string
  skill_display_name?: string
  timestamp: string
}

/**
 * 团队级结构变更实时同步 composable。
 *
 * 连接到 ws://host/ws/team/{teamId}，收到 project.* / team_skill.* /
 * team.member.* 事件后回调订阅方，让项目列表 / 团队 Skill 仓库 / 成员列表
 * 无需手动刷新即可更新。断线自动重连，团队切换时自动重连到新团队通道。
 */
export function useTeamSync(
  teamId: () => string | null,
  onEvent?: (evt: TeamSyncEvent) => void | Promise<void>,
) {
  const connected = ref(false)
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | undefined
  let manualClose = false
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

  function connect(tid: string, userId: string) {
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
    const url =
      cloudWsUrl(`/ws/team/${tid}`) +
      `?user_id=${encodeURIComponent(userId)}&token=${encodeURIComponent(token)}`

    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
    }

    ws.onmessage = (e) => {
      try {
        const evt: TeamSyncEvent = JSON.parse(e.data)
        if (onEvent) onEvent(evt)
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
      // 非主动关闭（断线/服务端重启）且仍停留在该团队时，定时重连
      if (
        !manualClose &&
        teamId() === tid &&
        authStore.user?.id === userId
      ) {
        reconnectTimer = setTimeout(() => connect(tid, userId), 3000)
      }
    }

    ws.onerror = () => {
      connected.value = false
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
    [teamId, () => authStore.user?.id ?? null],
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

  return { connected, disconnect }
}
