<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import type { ProjectInfo, ProjectSkillInfo } from '@/api/projects'
import {
  actionLabel,
  type NotificationMessage,
} from '@/stores/notificationStore'
import ProjectSkillActionIcon from '@/components/ProjectSkillActionIcon.vue'
import ProjectSkillStatusIcon from '@/components/ProjectSkillStatusIcon.vue'
import actionEmptyUrl from '@/img/status/action_empty.png'

const props = defineProps<{
  project: ProjectInfo | null
  skills: ProjectSkillInfo[]
  messages: NotificationMessage[]
  currentUserId?: string
}>()

const emit = defineEmits<{
  detail: [id: string]
}>()

const PROJECT_ACTIONS = new Set(['linked', 'deployed', 'unlinked', 'deleted'])
const selectedKey = ref('project')
const feedRef = ref<HTMLElement | null>(null)

const selectorItems = computed(() => [
  {
    key: 'project',
    name: '项目',
    description: props.project?.name || '当前项目',
    status: '',
  },
  ...props.skills.map((skill) => ({
    key: skill.skill_id,
    name: skill.display_name || skill.skill_id,
    description: skill.description || '暂无描述',
    status: skill.deployment?.status || 'none',
  })),
])

const visibleMessages = computed(() => {
  const filtered = selectedKey.value === 'project'
    ? props.messages.filter((message) => PROJECT_ACTIONS.has(message.action))
    : props.messages.filter((message) => message.skill_id === selectedKey.value)
  return [...filtered].reverse()
})

const selectedTitle = computed(() =>
  selectorItems.value.find((item) => item.key === selectedKey.value)?.name || '项目',
)

watch(
  () => props.skills.map((skill) => skill.skill_id),
  (skillIds) => {
    if (selectedKey.value !== 'project' && !skillIds.includes(selectedKey.value)) {
      selectedKey.value = 'project'
    }
  },
)

watch(
  () => visibleMessages.value.map((message) => message.id).join(','),
  async () => {
    await nextTick()
    if (feedRef.value) feedRef.value.scrollTop = feedRef.value.scrollHeight
  },
  { immediate: true },
)

function statusText(status: string): string {
  const labels: Record<string, string> = {
    none: '未部署',
    synced: '已同步',
    changed: '待推送',
    conflict: '冲突',
    outdated: '可更新',
    missing: '路径缺失',
    untracked: '已停止跟踪',
  }
  return labels[status] || '未部署'
}

function messageTitle(message: NotificationMessage): string {
  return `${actionLabel(message.action)} ${message.skill_display_name}`
}

function messageKind(action: string): string {
  if (['linked', 'created'].includes(action)) return 'positive'
  if (['unlinked', 'deleted', 'stopped'].includes(action)) return 'danger'
  if (['conflict', 'missing'].includes(action)) return 'warning'
  if (['pushed', 'pulled', 'merged', 'promoted', 'auto_promoted'].includes(action)) return 'sync'
  return 'neutral'
}

function activityIconAction(
  action: string,
): 'deploy' | 'push' | 'merge' | 'pull' | 'resume' | 'redeploy' | 'stop' | 'remove' {
  const actions: Record<
    string,
    'deploy' | 'push' | 'merge' | 'pull' | 'resume' | 'redeploy' | 'stop' | 'remove'
  > = {
    linked: 'deploy',
    created: 'deploy',
    deployed: 'deploy',
    pushed: 'push',
    updated: 'push',
    promoted: 'push',
    auto_promoted: 'push',
    pulled: 'pull',
    merged: 'merge',
    conflict: 'merge',
    resumed: 'resume',
    stopped: 'stop',
    missing: 'redeploy',
    unlinked: 'remove',
    deleted: 'remove',
  }
  return actions[action] || 'deploy'
}

function initials(name: string): string {
  return (name.trim().slice(0, 1) || '?').toUpperCase()
}

function formatMessageTime(timestamp: string): string {
  if (!timestamp) return ''
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp
  return date.toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function dateKey(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp.slice(0, 10)
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`
}

function formatMessageDate(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return timestamp.slice(0, 10)
  const today = new Date()
  const yesterday = new Date(today)
  yesterday.setDate(today.getDate() - 1)
  if (dateKey(timestamp) === dateKey(today.toISOString())) return '今天'
  if (dateKey(timestamp) === dateKey(yesterday.toISOString())) return '昨天'
  return date.toLocaleDateString('zh-CN', {
    month: 'long',
    day: 'numeric',
  })
}

function showDate(index: number): boolean {
  if (index === 0) return true
  return dateKey(visibleMessages.value[index - 1].timestamp)
    !== dateKey(visibleMessages.value[index].timestamp)
}
</script>

<template>
  <div class="activity-layout">
    <aside class="activity-selector" aria-label="动态范围">
      <button
        v-for="item in selectorItems"
        :key="item.key"
        class="activity-selector-card"
        :class="{ active: selectedKey === item.key }"
        type="button"
        @click="selectedKey = item.key"
      >
        <span v-if="item.key === 'project'" class="activity-project-icon" aria-hidden="true">
          <svg viewBox="0 0 1024 1024">
            <path d="M573.866667 208.213333h130.986666c157.44 0 234.24 84.053333 233.813334 256.426667v207.786667c0 164.693333-101.546667 266.24-266.666667 266.24H351.573333C187.306667 938.666667 85.333333 837.12 85.333333 672V351.573333C85.333333 174.933333 163.84 85.333333 318.72 85.333333h67.413333c39.68-0.426667 76.8 17.92 101.12 49.066667l37.546667 49.92c11.946667 14.933333 29.866667 23.893333 49.066667 23.893333zM314.453333 652.373333h395.093334c17.493333 0 31.573333-14.506667 31.573333-32a31.573333 31.573333 0 0 0-31.573333-32H314.453333c-17.92 0-32 14.08-32 32 0 17.493333 14.08 32 32 32z" />
          </svg>
        </span>
        <span
          v-else
          class="activity-skill-icon"
          :class="`status-${item.status}`"
          aria-hidden="true"
        >
          <ProjectSkillStatusIcon :status="item.status" />
        </span>
        <span class="activity-selector-copy">
          <strong>{{ item.name }}</strong>
          <small v-if="item.key === 'project'">关联、部署与移除</small>
          <small v-else>{{ statusText(item.status) }}</small>
        </span>
      </button>
    </aside>

    <section class="activity-conversation">
      <header class="activity-conversation-head">
        <div>
          <strong>{{ selectedTitle }}</strong>
          <span>动态记录</span>
        </div>
        <span class="activity-total">{{ visibleMessages.length }} 条</span>
      </header>

      <div ref="feedRef" class="activity-feed">
        <div v-if="visibleMessages.length === 0" class="activity-empty">
          <img class="activity-empty-image" :src="actionEmptyUrl" alt="" />
          <strong>{{ selectedTitle }}暂无动态</strong>
          <span>相关操作会在这里形成记录</span>
        </div>

        <template v-for="(message, index) in visibleMessages" :key="message.id">
          <div v-if="showDate(index)" class="activity-date">
            <span>{{ formatMessageDate(message.timestamp) }}</span>
          </div>
          <article
            class="activity-message"
            :class="{ own: message.user_id === currentUserId }"
          >
            <span class="activity-avatar">{{ initials(message.user_display_name) }}</span>
            <div class="activity-message-body">
              <div class="activity-message-meta">
                <strong>{{ message.user_display_name }}</strong>
                <time>{{ formatMessageTime(message.timestamp) }}</time>
              </div>
              <div
                class="activity-operation-card"
                :class="[
                  `kind-${messageKind(message.action)}`,
                  {
                    multiline:
                      (message.diff_summary && message.diff_summary !== '无改动') ||
                      message.change_items?.length,
                    'has-detail': message.change_items?.length,
                  },
                ]"
              >
                <span class="activity-operation-icon" aria-hidden="true">
                  <ProjectSkillActionIcon :action="activityIconAction(message.action)" />
                </span>
                <div class="activity-operation-copy">
                  <div class="activity-operation-title">
                    <strong>{{ messageTitle(message) }}</strong>
                    <span v-if="message.version">v{{ message.version }}</span>
                  </div>
                  <p
                    v-if="message.diff_summary && message.diff_summary !== '无改动'"
                  >
                    {{ message.diff_summary }}
                  </p>
                  <button
                    v-if="message.change_items?.length"
                    type="button"
                    @click="emit('detail', message.id)"
                  >
                    查看改动
                  </button>
                </div>
              </div>
            </div>
          </article>
        </template>
      </div>
    </section>
  </div>
</template>

<style scoped>
.activity-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 238px;
  gap: 18px;
  min-height: 560px;
}

.activity-selector {
  grid-column: 2;
  grid-row: 1;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
  min-height: calc(100vh - 176px);
  max-height: calc(100vh - 176px);
  box-sizing: border-box;
  padding: 8px;
  overflow-y: auto;
  background: #eef0f3;
  border: 1px solid #e4e7eb;
  border-radius: 14px;
}

.activity-selector-card {
  width: 100%;
  min-width: 0;
  min-height: 64px;
  padding: 10px;
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr);
  gap: 10px;
  align-items: center;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #4b5563;
  text-align: left;
  font: inherit;
  cursor: pointer;
  transition: background 0.16s ease, color 0.16s ease;
}

.activity-selector-card:hover:not(.active) {
  background: #dfe3e8;
  color: #151717;
}

.activity-selector-card.active {
  background: #151717;
  color: #ffffff;
}

.activity-project-icon,
.activity-skill-icon {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  border-radius: 50%;
  background: #ffffff;
  color: #151717;
}

.activity-project-icon {
  border: 1px solid #d8dde3;
}

.activity-project-icon svg {
  width: 21px;
  height: 21px;
  fill: currentColor;
}

.activity-skill-icon {
  --status-bg: #e5e7eb;
  position: relative;
  border: 3px solid #ffffff;
  outline: 1px solid #151717;
  background: var(--status-bg);
}

.activity-skill-icon svg {
  width: 22px;
  height: 22px;
  position: relative;
  z-index: 1;
  fill: currentColor;
}

.activity-skill-icon.status-synced { --status-bg: #8be6af; color: #126b35; }
.activity-skill-icon.status-changed { --status-bg: #ffd76f; color: #8a5300; }
.activity-skill-icon.status-outdated { --status-bg: #88c9ff; color: #075985; }
.activity-skill-icon.status-conflict { --status-bg: #ff9b9b; color: #991b1b; }
.activity-skill-icon.status-missing { --status-bg: #ffbd82; color: #9a3412; }
.activity-skill-icon.status-untracked { --status-bg: #c7cbd1; color: #4b5563; }

.activity-selector-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.activity-selector-copy strong,
.activity-selector-copy small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-selector-copy strong {
  font-size: 0.86rem;
  font-weight: 650;
}

.activity-selector-copy small {
  color: #8b929b;
  font-size: 0.72rem;
}

.activity-selector-card.active .activity-selector-copy small {
  color: #cbd0d6;
}

.activity-conversation {
  grid-column: 1;
  grid-row: 1;
  min-width: 0;
  min-height: 560px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: #ffffff;
  border: 0;
  border-radius: 0;
}

.activity-conversation-head {
  min-height: 64px;
  padding: 0 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  background: #ffffff;
  border-bottom: 2px solid #dfe3e8;
}

.activity-conversation-head > div {
  display: flex;
  align-items: flex-end;
  gap: 8px;
}

.activity-conversation-head span {
  color: #8b929b;
  font-size: 0.72rem;
}

.activity-conversation-head strong {
  color: #151717;
  font-size: 1.36rem;
  font-weight: 700;
  line-height: 1.2;
}

.activity-total {
  white-space: nowrap;
}

.activity-feed {
  height: 574px;
  padding: 22px 20px 28px;
  box-sizing: border-box;
  overflow-y: auto;
  scroll-behavior: smooth;
  background: #ffffff;
}

.activity-empty {
  height: 100%;
  min-height: 260px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: #9ca3af;
  text-align: center;
}

.activity-empty-image {
  width: min(420px, 92%);
  height: auto;
  margin: -24px 0 -90px;
  object-fit: contain;
}

.activity-empty strong {
  color: #151717;
  font-size: 1.08rem;
}

.activity-empty > span:last-child {
  font-size: 0.86rem;
}

.activity-date {
  width: min(100%, 760px);
  margin: 8px 0 16px;
  margin-right: auto;
  margin-left: auto;
  display: flex;
  align-items: center;
  justify-content: center;
}

.activity-date span {
  padding: 4px 10px;
  border-radius: 999px;
  background: #e7eaee;
  color: #7b828b;
  font-size: 0.68rem;
}

.activity-message {
  width: min(100%, 760px);
  margin-bottom: 18px;
  margin-right: auto;
  margin-left: auto;
  display: flex;
  align-items: flex-start;
  gap: 9px;
}

.activity-message.own {
  flex-direction: row-reverse;
}

.activity-avatar {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #dfe3e8;
  color: #374151;
  font-size: 0.76rem;
  font-weight: 700;
}

.activity-message.own .activity-avatar {
  display: none;
}

.activity-message-body {
  width: calc(100% - 41px);
  min-width: 0;
}

.activity-message:not(.own) .activity-message-body {
  width: fit-content;
  max-width: 74%;
}

.activity-message.own .activity-message-body {
  width: auto;
  max-width: 74%;
  margin-left: auto;
}

.activity-message-meta {
  margin-bottom: 5px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.activity-message.own .activity-message-meta {
  justify-content: flex-end;
}

.activity-message-meta strong {
  color: #4b5563;
  font-size: 0.74rem;
  font-weight: 600;
}

.activity-message-meta time {
  color: #9ca3af;
  font-size: 0.66rem;
}

.activity-operation-card {
  position: relative;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  gap: 11px;
  background: #eef0f2;
  border: 0;
  border-radius: 6px 18px 18px 18px;
  box-shadow: none;
}

.activity-message.own .activity-operation-card {
  padding: 12px 16px;
  background: #dbeafe;
  border: 0;
  border-radius: 18px 6px 18px 18px;
  box-shadow: none;
}

.activity-message .activity-operation-card.has-detail {
  padding-right: 100px;
}

.activity-operation-card.multiline {
  align-items: flex-start;
}

.activity-operation-card.multiline .activity-operation-icon {
  margin-top: 1px;
}

.activity-operation-icon {
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #e8ebef;
  color: #4b5563;
}

.kind-positive .activity-operation-icon { background: #dcfce7; color: #15803d; }
.kind-sync .activity-operation-icon { background: #bfdbfe; color: #1d4ed8; }
.kind-warning .activity-operation-icon { background: #fef3c7; color: #b45309; }
.kind-danger .activity-operation-icon { background: #fee2e2; color: #dc2626; }

.activity-operation-icon svg {
  width: 17px;
  height: 17px;
  fill: currentColor;
  stroke: currentColor;
  stroke-width: 10px;
  stroke-linejoin: round;
}

.activity-operation-copy {
  min-width: 0;
  flex: 1;
}

.activity-operation-title {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
}

.activity-operation-title strong {
  min-width: 0;
  color: #1f2328;
  font-size: 0.84rem;
  font-weight: 650;
}

.activity-operation-title span {
  flex: none;
  color: #8b929b;
  font-size: 0.66rem;
  font-family: 'JetBrains Mono', monospace;
}

.activity-operation-copy p {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 0.74rem;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.activity-operation-copy button {
  position: absolute;
  top: 9px;
  right: 12px;
  margin: 0;
  padding: 4px 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #4f46e5;
  font: inherit;
  font-size: 0.72rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease;
}

.activity-operation-copy button:hover {
  background: rgba(21, 23, 23, 0.08);
  text-decoration: none;
}

@media (max-width: 900px) {
  .activity-layout {
    grid-template-columns: minmax(0, 1fr);
    min-height: 0;
  }

  .activity-selector {
    grid-column: 1;
    grid-row: 1;
    flex-direction: row;
    min-height: 0;
    max-height: none;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .activity-selector-card {
    width: 210px;
    flex: 0 0 210px;
  }

  .activity-conversation {
    grid-column: 1;
    grid-row: 2;
    min-height: 480px;
  }

  .activity-feed {
    height: 500px;
    padding: 14px;
  }

  .activity-message-body {
    width: calc(100% - 41px);
  }
}

@media (max-width: 560px) {
  .activity-message-body {
    width: calc(100% - 41px);
  }

  .activity-conversation-head {
    padding: 0 14px;
  }
}
</style>
