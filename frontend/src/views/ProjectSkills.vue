<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useProjectSyncStore } from '@/stores/projectSyncStore'
import {
  listNativeSkills,
  listSkillVersions,
  type NativeSkillItem,
  type SkillVersionItem,
} from '@/api/skillStore'
import { getPlatformInstalledStatus } from '@/api/orchestration'
import { useNotificationStore, formatNotification } from '@/stores/notificationStore'
import { useSkillSync } from '@/composables/useSkillSync'
import { promptInput } from '@/composables/useInputDialog'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { toast } from '@/composables/useToast'
import AppTopNav from '@/components/AppTopNav.vue'
import FolderPicker from '@/components/FolderPicker.vue'
import SyncStatusBadge from '@/components/SyncStatusBadge.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import SkillMergeDialog from '@/components/SkillMergeDialog.vue'
import type {
  ChangeItem,
  UserSkillDeploymentInfo,
  MergePreviewResponse,
  MergedContent,
} from '@/api/projects'
import { parseUnifiedDiff, inlineSegments } from '@/utils/diffView'
import type { DiffRow, DiffRowType, InlinePair, SegOp } from '@/utils/diffView'
import { promptOpenAfterDeploy } from '@/utils/openAfterDeploy'
import {
  isValidVersionNumber,
  nextVersionNumber,
  versionNumberOf,
} from '@/utils/versionNumber'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectSyncStore()
const notificationStore = useNotificationStore()

const projectId = computed(() => route.params.id as string)

const { connected } = useSkillSync(() => projectId.value, async () => {
  await loadMessageHistory()
  await refreshLocalStatuses()
})

let pollTimer: ReturnType<typeof setInterval> | undefined

const showAddSkill = ref(false)
const showDeployModal = ref(false)
const deploySkillId = ref('')
const deployTool = ref<'cursor' | 'codex' | 'windsurf' | 'claude' | 'kiro' | 'trae' | 'qoder' | 'workbuddy'>('cursor')
const TOOL_OPTIONS = [
  { value: 'cursor', label: 'Cursor' },
  { value: 'codex', label: 'Codex' },
  { value: 'windsurf', label: 'Windsurf' },
  { value: 'claude', label: 'Claude Code' },
  { value: 'kiro', label: 'Kiro' },
  { value: 'trae', label: 'Trae' },
  { value: 'qoder', label: 'Qoder' },
  { value: 'workbuddy', label: 'WorkBuddy' },
]
const deployPath = ref('')
const deployOverwrite = ref(false)
const deployToGlobal = ref(false)
const deployLoading = ref(false)
const pushingId = ref('')
const pullingId = ref('')
// AI 辅助合并（冲突一键合并）
const mergingId = ref('')
const showMergeDialog = ref(false)
const mergePreviewData = ref<MergePreviewResponse | null>(null)
const mergeSubmitting = ref(false)
const mergeDeploymentId = ref('')
const mergeSkillName = ref('')

const localStatusMap = ref<Record<string, boolean>>({})
// 恢复跟踪时本地目录缺失 → 标记该部署需走「重新部署」（编排模式不打云端，纯前端提示）
const redeployHintIds = ref<Record<string, boolean>>({})
const teamRepoSkills = ref<NativeSkillItem[]>([])
const detailId = ref<string | null>(null)

const detailMsg = computed(() =>
  notificationStore.messages.find((m) => m.id === detailId.value) || null,
)

// —— Skill 列表滚动：超过 4 个时，列表区固定为「4 张卡片」高度并出现滚动条 ——
const SKILL_VISIBLE_LIMIT = 4
const skillListRef = ref<HTMLElement | null>(null)
const skillListMaxHeight = ref('')

/** 量取前 4 张卡片 + 间距的真实高度作为列表上限；不足 4 张则不限制。 */
function updateSkillListMaxHeight() {
  const el = skillListRef.value
  if (!el) {
    skillListMaxHeight.value = ''
    return
  }
  const cards = el.querySelectorAll<HTMLElement>('.skill-card')
  if (cards.length <= SKILL_VISIBLE_LIMIT) {
    skillListMaxHeight.value = ''
    return
  }
  const gap = parseFloat(getComputedStyle(el).rowGap || '12') || 12
  let h = 0
  for (let i = 0; i < SKILL_VISIBLE_LIMIT; i++) {
    h += cards[i].offsetHeight
  }
  h += gap * (SKILL_VISIBLE_LIMIT - 1)
  skillListMaxHeight.value = `${Math.ceil(h)}px`
}

async function scheduleSkillListMeasure() {
  await nextTick()
  updateSkillListMaxHeight()
}

watch(() => projectStore.projectSkills.length, scheduleSkillListMeasure)

onMounted(async () => {
  window.addEventListener('resize', updateSkillListMaxHeight)
  await projectStore.selectProject(projectId.value)
  await loadTeamRepoSkills()
  await loadMessageHistory()
  await refreshLocalStatuses()
  scheduleSkillListMeasure()

  // 轮询兜底：即使 WebSocket 不可用，项目动态与本地状态也能准实时更新，无需手动刷新
  pollTimer = setInterval(async () => {
    await loadMessageHistory()
    await refreshLocalStatuses()
  }, 8000)
})

onUnmounted(() => {
  window.removeEventListener('resize', updateSkillListMaxHeight)
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = undefined
  }
})

async function loadMessageHistory() {
  const res = await projectStore.fetchChanges(projectId.value, 0)
  if (res?.success && res.changes) {
    const items = res.changes.map((c: any) => ({
      id: c.id,
      user_display_name: c.user_display_name || c.user_id,
      skill_display_name: c.skill_display_name || c.skill_id,
      action: c.action,
      timestamp: c.created_at || '',
      change_items: c.change_items || [],
      diff_summary: c.diff_summary || '',
    }))
    notificationStore.loadHistory(items)
  }
}

async function refreshLocalStatuses() {
  for (const skill of projectStore.projectSkills) {
    const dep = skill.deployment
    if (dep && dep.tracking_enabled) {
      const res = await projectStore.checkLocalStatus(dep.id)
      if (res.success) {
        localStatusMap.value = {
          ...localStatusMap.value,
          [dep.id]: res.has_local_changes,
        }
      }
    }
  }
}

function hasLocalChanges(dep?: UserSkillDeploymentInfo | null): boolean {
  if (!dep) return false
  if (dep.id in localStatusMap.value) return localStatusMap.value[dep.id]
  return dep.local_dirty
}

function openDetail(id: string) {
  detailId.value = id
}

function closeDetail() {
  detailId.value = null
}

function formatVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '空'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (Array.isArray(v)) return v.join(', ') || '空'
  return String(v)
}

// —— diff 详情高亮（diff-match-patch） ——
function fieldSegs(item: ChangeItem): InlinePair {
  return inlineSegments(formatVal(item.old), formatVal(item.new))
}

function bodyRows(item: ChangeItem): DiffRow[] {
  return parseUnifiedDiff(item.diff || '')
}

function segClass(op: SegOp): string {
  if (op < 0) return 'seg-del'
  if (op > 0) return 'seg-add'
  return ''
}

function rowSign(type: DiffRowType): string {
  if (type === 'add') return '+'
  if (type === 'del') return '-'
  return ''
}

function resourceVerb(change?: string): string {
  if (change === 'added') return '新增'
  if (change === 'removed') return '删除'
  return '修改'
}

async function loadTeamRepoSkills() {
  const teamId = projectStore.currentProject?.team_id
  if (!teamId) {
    teamRepoSkills.value = []
    return
  }
  try {
    const res = await listNativeSkills('team')
    teamRepoSkills.value = res.success
      ? res.skills.filter((s) => s.team_id === teamId)
      : []
  } catch {
    teamRepoSkills.value = []
  }
}

function openAddSkill() {
  showAddSkill.value = true
  loadTeamRepoSkills()
}

const availableSkills = computed(() => {
  const linked = new Set(projectStore.projectSkills.map((s) => s.skill_id))
  return teamRepoSkills.value.filter((s) => !linked.has(s.id))
})

async function addSkillToProject(skillId: string) {
  const res = await projectStore.addSkill(projectId.value, skillId)
  if (!res.success) {
    toast.error(res.error || '添加失败')
  } else {
    showAddSkill.value = false
    toast.success('已添加 Skill 到项目')
  }
}

async function removeSkill(skillId: string) {
  const skill = projectStore.projectSkills.find((s) => s.skill_id === skillId)
  if (skill?.deployment?.tracking_enabled) {
    toast.warning('该 Skill 正在本机跟踪中，请先「停止跟踪」再移除')
    return
  }
  const ok = await confirmDialog({
    title: '移除 Skill',
    message: '确认从项目移除该 Skill？移除后项目成员将无法再部署它。',
    confirmText: '移除',
    danger: true,
  })
  if (!ok) return
  const res = await projectStore.removeSkill(projectId.value, skillId)
  if (!res.success) {
    toast.error(res.error || '移除失败')
  } else {
    toast.success('已从项目移除该 Skill')
  }
}

function openDeploy(skillId: string) {
  deploySkillId.value = skillId
  deployTool.value = 'cursor'
  deployPath.value = ''
  deployOverwrite.value = false
  deployToGlobal.value = false
  showDeployModal.value = true
}

async function submitDeploy() {
  if (!deploySkillId.value) return
  if (!deployPath.value.trim()) {
    toast.warning('请选择本机项目路径')
    return
  }
  deployLoading.value = true
  // 基础动作：部署到项目（带跟踪同步）。
  const res = await projectStore.deploySkill(
    projectId.value,
    deploySkillId.value,
    deployTool.value,
    deployPath.value.trim(),
    deployOverwrite.value,
  )
  if (!res.success) {
    deployLoading.value = false
    toast.error(res.error || '部署失败')
    return
  }
  // 附加动作：勾选「同时部署到全局」→ 再落一份到 ~/.{tool}/skills（一次性、不跟踪、同名覆盖）。
  if (deployToGlobal.value) {
    const gres = await projectStore.deploySkillGlobal(
      projectId.value,
      deploySkillId.value,
      deployTool.value,
    )
    if (!gres.success) {
      deployLoading.value = false
      toast.error(`已部署到项目，但全局部署失败：${gres.error || ''}`)
      return
    }
  }
  deployLoading.value = false
  toast.success(deployToGlobal.value ? '已部署到项目并同步到全局' : '已部署到项目')
  // 关掉部署弹窗后再询问是否打开工具（确认框是全局浮层，避免与弹窗叠加）。
  const openedTool = deployTool.value
  const openedPath = deployPath.value.trim()
  showDeployModal.value = false
  await promptOpenAfterDeploy(openedTool, openedPath)
}

async function stopTracking(deploymentId: string) {
  await projectStore.stopTracking(deploymentId)
}

async function resumeTracking(deploymentId: string) {
  const res = await projectStore.resumeTracking(deploymentId)
  if (!res.success) {
    if (res.status === 'missing') {
      redeployHintIds.value = { ...redeployHintIds.value, [deploymentId]: true }
      toast.warning('本地部署目录缺失，请点「重新部署」')
    } else {
      toast.error(res.error || '恢复跟踪失败')
    }
    return
  }
  const next = { ...redeployHintIds.value }
  delete next[deploymentId]
  redeployHintIds.value = next
  toast.success('已恢复跟踪')
  await refreshLocalStatuses()
}

async function pushDeploy(deploymentId: string) {
  const deployment = findDeploymentById(deploymentId)
  if (!deployment) {
    toast.error('未找到部署记录')
    return
  }
  const proceed = await confirmDialog({
    title: '推送到团队仓库',
    message: '推送将把本地改动同步到团队仓库，其他成员可拉取更新，是否继续？',
    confirmText: '继续',
  })
  if (!proceed) return
  // 是否成版本：选「更新版本」则本次推送创建一条版本快照（可在 Skill 详情页查看/回滚）。
  const createVersion = await confirmDialog({
    title: '是否更新版本号？',
    message:
      '更新版本：本次推送可确认或填写具体版本号（默认次版本 +1，可在 Skill 详情页查看/回滚）。\n仅同步：只同步内容，不创建版本。',
    confirmText: '更新版本',
    cancelText: '仅同步',
  })
  let versionNumber = ''
  let versionLabel = ''
  if (createVersion) {
    let currentVersions: SkillVersionItem[] = []
    try {
      const res = await listSkillVersions(deployment.team_skill_id)
      if (res.success) currentVersions = res.versions
    } catch {
      // 获取建议版本失败时仍预填首版，由后端做最终校验。
    }
    const enteredVersion = await promptInput({
      title: '新版本号',
      message: '版本号格式为 x.y；默认次版本加 1，也可以直接覆盖输入。',
      defaultValue: nextVersionNumber(currentVersions),
      placeholder: '例如：1.2',
      confirmText: '下一步',
      maxlength: 32,
    })
    if (enteredVersion === null) return
    versionNumber = enteredVersion.trim()
    if (!isValidVersionNumber(versionNumber)) {
      toast.error('版本号格式不正确，请输入 x.y，例如 1.2')
      return
    }
    if (
      currentVersions.some(
        (version) => versionNumberOf(version) === versionNumber,
      )
    ) {
      toast.error(`版本号 v${versionNumber} 已存在`)
      return
    }
    // 应用内输入框（替代 Electron 不支持的 window.prompt）；取消视为不填备注，仍继续推送。
    const label = await promptInput({
      title: '新版本备注',
      message: '可为该版本填写备注/标签，用于在 Skill 详情页区分版本（可留空）。',
      placeholder: '例如：修复样式 / 调整提示词',
      confirmText: '确定',
      maxlength: 100,
    })
    versionLabel = (label ?? '').trim()
  }
  pushingId.value = deploymentId
  const res = await projectStore.push(deploymentId, {
    createVersion,
    versionNumber,
    versionLabel,
  })
  pushingId.value = ''
  if (!res.success) {
    if (res.conflict) {
      toast.warning('团队仓库已更新，请先点"更新本地"再推送')
    } else {
      toast.error(res.error || '推送失败')
    }
    await refreshLocalStatuses()
    return
  }
  if (res.no_change) {
    toast.info('本地无改动，无需推送')
  } else if (res.version) {
    toast.success(
      `已推送并同步到项目，已创建版本 v${versionNumberOf(res.version)}`,
    )
  } else {
    toast.success('已推送并同步到项目')
  }
  await loadMessageHistory()
  await refreshLocalStatuses()
}

async function pullUpdate(deploymentId: string, status?: string) {
  const localConflict = status === 'conflict'
  const message = localConflict
    ? '本地有未推送改动，更新将覆盖本地改动，是否继续？'
    : '将拉取团队最新内容覆盖到本地部署目录，是否继续？'
  const ok = await confirmDialog({
    title: '更新本地',
    message,
    confirmText: '继续',
    danger: localConflict,
  })
  if (!ok) return
  pullingId.value = deploymentId
  let res = await projectStore.pullUpdate(deploymentId, localConflict)
  if (!res.success && res.conflict && !localConflict) {
    const overwrite = await confirmDialog({
      title: '覆盖本地改动',
      message: '本地有未推送改动，确认覆盖本地后更新？',
      confirmText: '覆盖更新',
      danger: true,
    })
    if (overwrite) {
      res = await projectStore.pullUpdate(deploymentId, true)
    } else {
      pullingId.value = ''
      return
    }
  }
  pullingId.value = ''
  if (!res.success) {
    toast.error(res.error || '更新失败')
    return
  }
  toast.success('已更新本地到团队最新')
  // 全局部署不跟踪更新；若该 Skill 也已全局部署，提示是否把本次更新同步覆盖到全局。
  await maybePullToGlobal(deploymentId)
  await loadMessageHistory()
  await refreshLocalStatuses()
}

function deploymentSkillName(deploymentId: string): string {
  for (const s of projectStore.projectSkills) {
    if (s.deployment?.id === deploymentId) return s.display_name || s.skill_id
  }
  return ''
}

/** AI 合并第一步：取三方合并预览并打开预览框。 */
async function openMerge(deployment: UserSkillDeploymentInfo) {
  mergingId.value = deployment.id
  const res = await projectStore.mergePreview(deployment.id)
  mergingId.value = ''
  if (!res.success) {
    toast.error(res.error || 'AI 合并预览失败')
    return
  }
  mergePreviewData.value = res
  mergeDeploymentId.value = deployment.id
  mergeSkillName.value = deploymentSkillName(deployment.id)
  showMergeDialog.value = true
}

/** AI 合并第二步：把（可能编辑过的）合并稿提交到团队仓库并覆盖本地。 */
async function onMergeConfirm(merged: MergedContent) {
  if (!mergePreviewData.value) return
  mergeSubmitting.value = true
  const res = await projectStore.mergeCommit(
    mergeDeploymentId.value,
    merged,
    mergePreviewData.value.theirs_hash,
  )
  mergeSubmitting.value = false
  showMergeDialog.value = false
  if (!res.success) {
    if (res.conflict) {
      toast.warning('团队仓库又更新了，请重新点「AI 合并」')
    } else {
      toast.error(res.error || '合并提交失败')
    }
    await refreshLocalStatuses()
    return
  }
  toast.success('已 AI 合并并提交到团队仓库')
  await loadMessageHistory()
  await refreshLocalStatuses()
}

/** 按部署 id 在当前项目 Skill 列表里查回部署对象（取 skill_id / tool_type）。 */
function findDeploymentById(deploymentId: string): UserSkillDeploymentInfo | null {
  for (const s of projectStore.projectSkills) {
    if (s.deployment?.id === deploymentId) return s.deployment
  }
  return null
}

/**
 * 项目级「更新本地」成功后的可选附加动作：
 * 全局部署是一次性安装、不跟踪更新，故团队更新拉到本地后不会自动同步到全局。
 * 这里探测本机平台目录是否存在同名同平台的全局副本，若有则提示用户是否一并覆盖更新到全局。
 */
async function maybePullToGlobal(deploymentId: string) {
  const dep = findDeploymentById(deploymentId)
  if (!dep) return
  const tool = dep.tool_type as 'cursor' | 'codex' | 'windsurf' | 'claude' | 'kiro' | 'trae' | 'qoder' | 'workbuddy'
  let isGlobal = false
  try {
    const installed = await getPlatformInstalledStatus()
    isGlobal = !!installed[dep.team_skill_id]?.[tool]
  } catch {
    // 本地代理不可达（如 web 灰度）→ 无法判定全局状态，静默跳过提示
    return
  }
  if (!isGlobal) return
  const ok = await confirmDialog({
    title: '同步到全局',
    message: '该 Skill 也已全局部署，是否将本次更新同步到全局（用新内容覆盖旧的全局副本）？',
    confirmText: '同步到全局',
  })
  if (!ok) return
  const gres = await projectStore.deploySkillGlobal(projectId.value, dep.team_skill_id, tool)
  if (gres.success) {
    toast.success('已更新本地并同步到全局')
  } else {
    toast.error(`本地已更新，但全局同步失败：${gres.error || ''}`)
  }
}

function statusLabel(status?: string): string {
  const labels: Record<string, string> = {
    synced: '已同步',
    changed: '待推送',
    conflict: '冲突',
    outdated: '可更新',
    missing: '路径缺失',
    untracked: '已停止跟踪',
  }
  return labels[status || ''] || '未部署'
}

function formatTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts.slice(11, 19) || ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function goBack() {
  router.push('/team/projects')
}
</script>

<template>
  <div class="project-page">
    <AppTopNav />

    <div class="content">
      <!-- 顶部栏：参考 SKILL 详情（圆形返回 + 标题 + 同步徽章） -->
      <div class="toolbar">
        <div class="toolbar-left">
          <button class="btn-back" @click="goBack" title="返回" aria-label="返回">
            <svg viewBox="0 0 1024 1024" width="22" height="22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M515.582162 1023.994371A516.343116 516.343116 0 0 1 204.957513 921.646875a502.014467 502.014467 0 0 1-113.60572-122.816995A486.662342 486.662342 0 0 1 20.73202 642.238212a511.737479 511.737479 0 0 1 990.723759-259.962639 40.938998 40.938998 0 0 1-3.582162 29.169036 36.333361 36.333361 0 0 1-23.539924 17.399074 36.845098 36.845098 0 0 1-29.169036-3.582162 38.892048 38.892048 0 0 1-18.42255-23.539924 436.000332 436.000332 0 0 0-420.13647-324.953299 446.235081 446.235081 0 0 0-111.047033 14.328649 434.976857 434.976857 0 1 0 538.859565 497.40883 37.868573 37.868573 0 0 1 37.356836-32.239462h6.652588a39.915523 39.915523 0 0 1 25.075136 15.863862 38.380311 38.380311 0 0 1 6.14085 28.657299 511.737479 511.737479 0 0 1-374.591835 405.296083 460.563731 460.563731 0 0 1-129.469582 17.910812z" fill="currentColor"></path>
              <path d="M512 775.801694a35.821624 35.821624 0 0 1-27.122086-11.769962l-225.164491-224.652753a38.892048 38.892048 0 0 1 0-54.244173l225.164491-224.652753a39.915523 39.915523 0 0 1 27.122086-11.769962 37.868573 37.868573 0 0 1 27.122086 11.769962 39.915523 39.915523 0 0 1 11.769962 27.122086 35.821624 35.821624 0 0 1-11.769962 27.122086l-158.638618 158.638619h358.216235a38.892048 38.892048 0 1 1 0 77.272359h-358.216235l159.150356 159.150356a38.892048 38.892048 0 0 1 11.769962 27.122086 37.868573 37.868573 0 0 1-11.769962 27.122087 36.845098 36.845098 0 0 1-27.633824 11.769962z" fill="currentColor"></path>
            </svg>
          </button>
          <h2 class="editor-title">{{ projectStore.currentProject?.name || '项目' }}</h2>
          <SyncStatusBadge :connected="connected" />
        </div>
      </div>

      <!-- 项目信息 -->
      <div class="project-info">
        <p class="desc">{{ projectStore.currentProject?.description || '暂无描述' }}</p>
      </div>

      <!-- Skill 列表 -->
      <div class="section-header">
        <h3>项目 Skill</h3>
        <button class="btn-sm btn-primary" @click="openAddSkill">
          + 关联 Skill
        </button>
      </div>

      <div
        ref="skillListRef"
        class="skill-list"
        :class="{ 'is-scrollable': !!skillListMaxHeight }"
        :style="skillListMaxHeight ? { maxHeight: skillListMaxHeight } : undefined"
      >
        <div
          v-for="skill in projectStore.projectSkills"
          :key="skill.skill_id"
          class="skill-card"
        >
          <div class="skill-main">
            <div class="skill-name-row">
              <h4 class="skill-name" :title="'查看 ' + (skill.display_name || skill.skill_id) + ' 详情'" @click="router.push('/skills/' + skill.skill_id)">
                {{ skill.display_name || skill.skill_id }}
              </h4>
              <span v-if="hasLocalChanges(skill.deployment)" class="dirty-badge">
                有改动待推送
              </span>
            </div>
            <p :title="skill.description || ''">{{ skill.description || '暂无描述' }}</p>
            <div class="deployment-line" :class="skill.deployment?.status || 'none'" :title="skill.deployment?.install_path || ''">
              {{ statusLabel(skill.deployment?.status) }}
              <template v-if="skill.deployment">
                · {{ skill.deployment.tool_type }}
                · {{ skill.deployment.install_path }}
              </template>
            </div>
          </div>
          <div class="skill-right">
          <div class="skill-meta">
            <span class="version">v{{ skill.version }}</span>
            <span class="hash" :title="skill.content_hash">
              {{ skill.content_hash?.slice(0, 8) || '--' }}
            </span>
          </div>
          <div class="skill-actions">
            <button class="btn-sm btn-soft" @click="router.push('/skills/' + skill.skill_id)">详情</button>
            <button
              v-if="!skill.deployment"
              class="btn-sm btn-primary"
              @click="openDeploy(skill.skill_id)"
            >
              部署
            </button>
            <button
              v-if="skill.deployment?.tracking_enabled && hasLocalChanges(skill.deployment)"
              class="btn-sm btn-primary"
              :disabled="pushingId === skill.deployment.id"
              @click="pushDeploy(skill.deployment.id)"
            >
              {{ pushingId === skill.deployment.id ? '推送中...' : '推送' }}
            </button>
            <button
              v-if="skill.deployment && skill.deployment.status === 'conflict'"
              class="btn-sm btn-merge"
              :disabled="mergingId === skill.deployment.id"
              @click="openMerge(skill.deployment)"
            >
              {{ mergingId === skill.deployment.id ? '分析中...' : 'AI 合并' }}
            </button>
            <button
              v-if="skill.deployment && ['outdated', 'conflict'].includes(skill.deployment.status)"
              class="btn-sm btn-primary"
              :disabled="pullingId === skill.deployment.id"
              @click="pullUpdate(skill.deployment.id, skill.deployment.status)"
            >
              {{ pullingId === skill.deployment.id ? '更新中...' : '更新本地' }}
            </button>
            <button
              v-if="skill.deployment && !skill.deployment.tracking_enabled && skill.deployment.status !== 'missing' && !redeployHintIds[skill.deployment.id]"
              class="btn-sm btn-primary"
              @click="resumeTracking(skill.deployment.id)"
            >
              恢复跟踪
            </button>
            <button
              v-if="skill.deployment && (skill.deployment.status === 'missing' || redeployHintIds[skill.deployment.id])"
              class="btn-sm btn-primary"
              @click="openDeploy(skill.skill_id)"
            >
              重新部署
            </button>
            <button
              v-if="skill.deployment?.tracking_enabled"
              class="btn-sm btn-soft"
              @click="stopTracking(skill.deployment.id)"
            >
              停止跟踪
            </button>
            <button class="btn-sm btn-danger" @click="removeSkill(skill.skill_id)">移除</button>
          </div>
          </div>
        </div>
      </div>

      <div v-if="projectStore.projectSkills.length === 0" class="empty-hint">
        暂无关联 Skill，点击"+ 关联 Skill"添加
      </div>

      <!-- 项目动态：与「项目 Skill」同级，标题置于卡片之外 -->
      <div class="section-header section-header-log">
        <h3>项目动态</h3>
      </div>
      <div class="message-log">
        <div v-if="notificationStore.messages.length === 0" class="empty-hint">
          暂无动态
        </div>
        <ul v-else>
          <li v-for="msg in notificationStore.messages.slice(0, 20)" :key="msg.id">
            <div class="msg-row">
              <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
              <span class="msg-text">{{ formatNotification(msg) }}</span>
              <button
                v-if="msg.change_items && msg.change_items.length"
                class="detail-btn"
                @click="openDetail(msg.id)"
              >
                详情
              </button>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <!-- 添加 Skill 弹窗 -->
    <BaseModal v-model="showAddSkill" title="关联 Skill 到项目">
      <p class="hint">从团队仓库选择 Skill。添加后只进入项目列表，不会自动部署到本地目录。</p>

      <div v-if="availableSkills.length === 0" class="empty-hint">
        所有 Skill 已关联，或 Skill 库为空
      </div>

      <ul class="add-skill-list">
        <li v-for="skill in availableSkills" :key="skill.id">
          <div>
            <strong>{{ skill.display_name || skill.id }}</strong>
            <span class="sub">{{ skill.short_description }}</span>
          </div>
          <button class="btn-sm btn-primary" @click="addSkillToProject(skill.id)">
            添加
          </button>
        </li>
      </ul>

    </BaseModal>

    <BaseModal v-model="showDeployModal" title="部署 Skill 到本机项目">
      <p class="hint">部署后才会跟踪该本地 Skill 实例，团队仓库自动热更新由团队设置控制。</p>

      <div class="field">
        <label>Vibe Coding 工具</label>
        <BaseSelect v-model="deployTool" :options="TOOL_OPTIONS" />
      </div>

      <div class="field">
        <label>本机项目路径</label>
        <FolderPicker v-model="deployPath" placeholder="点击选择项目文件夹" />
      </div>

      <label class="check-line">
        <input v-model="deployToGlobal" type="checkbox" />
        <span>同时部署到全局（额外安装到 ~/.{{ deployTool }}/skills，对所有项目生效；一次性、不跟踪同步）</span>
      </label>

      <label class="check-line">
        <input v-model="deployOverwrite" type="checkbox" />
        <span>覆盖已存在的同名 Skill</span>
      </label>

      <template #footer>
        <button class="btn-sm btn-primary" :disabled="deployLoading" @click="submitDeploy">
          {{ deployLoading ? '部署中...' : '部署' }}
        </button>
      </template>
    </BaseModal>

    <!-- 改动详情弹窗：diff-match-patch 高亮 -->
    <BaseModal
      :model-value="!!detailMsg"
      title="改动详情"
      :width="760"
      @update:model-value="closeDetail"
    >
      <template v-if="detailMsg">
          <p class="diff-meta">
            {{ detailMsg.user_display_name }} · {{ detailMsg.skill_display_name }}
            · {{ formatTime(detailMsg.timestamp) }}
          </p>
          <p v-if="detailMsg.diff_summary" class="diff-summary">{{ detailMsg.diff_summary }}</p>

          <div class="diff-body">
            <div
              v-for="(item, i) in detailMsg.change_items"
              :key="i"
              class="diff-block"
            >
              <!-- 字段改动：行内字符级高亮 -->
              <template v-if="item.kind === 'field'">
                <div class="diff-block-head">{{ item.label }}</div>
                <div class="diff-line del">
                  <span class="ln">-</span>
                  <span class="code"><span
                    v-for="(s, j) in fieldSegs(item).left"
                    :key="j"
                    :class="segClass(s.op)"
                  >{{ s.text }}</span></span>
                </div>
                <div class="diff-line add">
                  <span class="ln">+</span>
                  <span class="code"><span
                    v-for="(s, j) in fieldSegs(item).right"
                    :key="j"
                    :class="segClass(s.op)"
                  >{{ s.text }}</span></span>
                </div>
              </template>

              <!-- 正文改动：逐行 + 替换行的行内高亮 -->
              <template v-else-if="item.kind === 'body'">
                <div class="diff-block-head">
                  正文 VibeSkill.md
                  <span class="counts">
                    <span class="add">+{{ item.added_lines || 0 }}</span>
                    <span class="del">-{{ item.removed_lines || 0 }}</span>
                  </span>
                </div>
                <div class="diff-code">
                  <div
                    v-for="(row, k) in bodyRows(item)"
                    :key="k"
                    class="diff-line"
                    :class="row.type"
                  >
                    <span class="ln">{{ rowSign(row.type) }}</span>
                    <span class="code"><template v-if="row.segs"><span
                      v-for="(s, j) in row.segs"
                      :key="j"
                      :class="segClass(s.op)"
                    >{{ s.text }}</span></template><template v-else>{{ row.text }}</template></span>
                  </div>
                </div>
                <p v-if="item.diff_truncated" class="diff-trunc">
                  差异较长，仅展示前 40 行变更
                </p>
              </template>

              <!-- 资源改动 -->
              <template v-else>
                <div class="diff-resource" :class="item.change">
                  <span class="res-verb">{{ resourceVerb(item.change) }}</span>
                  {{ item.label }} · {{ item.path }}
                </div>
              </template>
            </div>
          </div>

      </template>
    </BaseModal>

    <SkillMergeDialog
      v-model="showMergeDialog"
      :skill-name="mergeSkillName"
      :preview="mergePreviewData"
      :submitting="mergeSubmitting"
      @confirm="onMergeConfirm"
    />
  </div>
</template>

<style scoped>
.project-page {
  min-height: 100vh;
  background: var(--canvas);
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
}

/* —— 顶部栏：参考 SKILL 详情（透明、落在画布上） —— */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.btn-back {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #2c2c2c;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transition: background 0.18s ease, color 0.18s ease, transform 0.12s ease,
    box-shadow 0.18s ease;
}
.btn-back svg { display: block; transition: transform 0.18s ease; }
.btn-back:hover { background: #f0f1f2; color: #151717; box-shadow: 0 2px 8px rgba(21, 23, 23, 0.08); }
.btn-back:hover svg { transform: scale(1.18); }
.btn-back:active { background: #e2e4e6; transform: scale(0.86); box-shadow: none; }

.editor-title {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 600;
  line-height: 1;
  letter-spacing: -0.01em;
  color: #151717;
}

.content {
  max-width: 960px;
  margin: 0 auto;
  padding: 1.5rem 24px 2rem;
}

.project-info .desc {
  color: #6b7280;
  font-size: 0.88rem;
  margin: 0 0 24px;
}

.section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.section-header h3 {
  margin: 0;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #151717;
}

.skill-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

/* 超过 4 个 Skill 时固定高度并滚动；留出右侧间距避免滚动条压住卡片 */
.skill-list.is-scrollable {
  overflow-y: auto;
  padding-right: 6px;
}

.skill-card {
  display: flex;
  align-items: center;
  gap: 16px;
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 16px;
  padding: 16px 20px;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

/* Skill 名称 + 「有改动待推送」角标同行（角标在名称右侧） */
.skill-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}

.skill-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 4px 16px rgba(21, 23, 23, 0.05);
}

.skill-main {
  flex: 1;
  min-width: 0;
}

.skill-main h4 {
  margin: 0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #151717;
}

.skill-main h4.skill-name {
  cursor: pointer;
  transition: color 0.15s ease;
}

.skill-main h4.skill-name:hover {
  color: #4f46e5;
  text-decoration: underline;
}

.skill-main p {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.5;
  color: #6b7280;
  /* 描述禁止换行：单行展示，超出截断省略号 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.deployment-line {
  margin-top: 8px;
  font-size: 0.76rem;
  color: #9ca3af;
  /* 部署路径固定一行，过长截断省略号 */
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.deployment-line.synced {
  color: #16a34a;
}

.deployment-line.changed {
  color: #b45309;
}

.deployment-line.conflict,
.deployment-line.missing {
  color: #dc2626;
}

/* 右侧组：版本号 + 操作按钮，与左侧描述以竖线分界，内容整体靠左对齐。
   固定宽度让各卡片的分界线位置保持一致；宽度需容纳最多 4 个按钮（详情+主操作+停止跟踪+移除），避免换行。 */
.skill-right {
  flex: none;
  width: 384px;
  display: flex;
  align-items: center;
  gap: 16px;
}

/* 分割线：加粗的胶囊形竖条（圆角两端） */
.skill-right::before {
  content: '';
  flex: none;
  align-self: stretch;
  width: 2px;
  margin: 2px 0;
  border-radius: 999px;
  background: #cbd1d8;
}

.skill-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.version {
  font-size: 0.82rem;
  color: #4f46e5;
  font-weight: 600;
}

.hash {
  font-size: 0.7rem;
  color: #b6bcc4;
  font-family: 'JetBrains Mono', monospace;
}

.skill-actions {
  flex: 1;
  display: flex;
  gap: 10px;
  flex-wrap: nowrap;
  /* 按钮之间固定间距，整组在右侧空余空间内居中 */
  justify-content: center;
}

.skill-actions .btn-sm {
  white-space: nowrap;
}

/* 移除：纯色危险按钮（与 SKILL 详情页「删除」一致：实底红、白字）。
   用 .skill-actions 前缀提高优先级，确保覆盖后面定义的 .btn-sm 基础样式。 */
.skill-actions .btn-danger {
  background: #dc2626;
  border-color: #dc2626;
  color: #ffffff;
}

.skill-actions .btn-danger:hover {
  background: #b91c1c;
  border-color: #b91c1c;
  color: #ffffff;
}

/* 详情 / 停止跟踪：纯色次级按钮（实底浅灰、无描边，区别于主操作的深色与危险操作的红色） */
.skill-actions .btn-soft {
  background: #eef0f2;
  border-color: #eef0f2;
  color: #374151;
}

.skill-actions .btn-soft:hover {
  background: #e2e5e8;
  border-color: #e2e5e8;
  color: #151717;
}

.section-header-log {
  margin-top: 40px;
}

.message-log {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 16px;
  padding: 16px 20px;
  /* 保证空状态有高度，并让内容（含「暂无动态」）垂直居中 */
  min-height: 88px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

/* 空状态文案在动态卡片内垂直居中：去掉通用 empty-hint 的顶部外边距 */
.message-log > .empty-hint {
  margin-top: 0;
}

.message-log ul {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 320px;
  overflow-y: auto;
}

.message-log li {
  font-size: 0.84rem;
  padding: 8px 0;
  border-bottom: 1px solid #f3f4f6;
}

.msg-row {
  display: flex;
  gap: 12px;
  align-items: center;
}

/* 项目动态「详情」：无边框文字链接，悬停下划线反馈与 Skill 名称一致（靛蓝 + 下划线） */
.detail-btn {
  margin-left: auto;
  flex-shrink: 0;
  padding: 2px 0;
  font-size: 0.76rem;
  border: none;
  background: transparent;
  color: #6b7280;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.15s ease;
}

.detail-btn:hover {
  color: #4f46e5;
  text-decoration: underline;
}

/* —— 改动详情弹窗 —— */
.diff-meta {
  margin: 0 0 4px;
  font-size: 0.76rem;
  color: #9ca3af;
}

.diff-summary {
  margin: 0 0 14px;
  font-size: 0.84rem;
  color: #6b7280;
}

.diff-body {
  max-height: 62vh;
  overflow: auto;
}

.diff-block {
  margin-bottom: 16px;
}

.diff-block-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 0.76rem;
  color: #4b5563;
  margin-bottom: 6px;
  font-weight: 600;
}

.diff-block-head .counts {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 400;
}

.diff-block-head .counts .add {
  color: #16a34a;
  margin-right: 6px;
}

.diff-block-head .counts .del {
  color: #dc2626;
}

.diff-code {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.diff-line {
  display: flex;
  font-family: 'JetBrains Mono', 'SFMono-Regular', Consolas, monospace;
  font-size: 12.5px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.diff-line .ln {
  flex-shrink: 0;
  width: 22px;
  text-align: center;
  color: #b6bcc4;
  user-select: none;
}

.diff-line .code {
  flex: 1;
  padding-right: 8px;
}

.diff-line.add {
  background: rgba(22, 163, 74, 0.08);
}

.diff-line.add .ln {
  color: #16a34a;
}

.diff-line.del {
  background: rgba(220, 38, 38, 0.07);
}

.diff-line.del .ln {
  color: #dc2626;
}

.diff-line.hunk {
  background: #f6f7f8;
  color: #6b7280;
}

.diff-line.context {
  color: #6b7280;
}

/* 行内字符级高亮（被替换/新增的具体片段） */
.seg-del {
  background: rgba(220, 38, 38, 0.18);
  border-radius: 2px;
}

.seg-add {
  background: rgba(22, 163, 74, 0.2);
  border-radius: 2px;
}

.diff-trunc {
  margin: 6px 0 0;
  font-size: 0.76rem;
  color: #9ca3af;
}

.diff-resource {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.82rem;
  color: #4b5563;
}

.diff-resource .res-verb {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 6px;
  margin-right: 8px;
  font-size: 0.76rem;
}

.diff-resource.added .res-verb {
  background: #f0fdf4;
  color: #15803d;
}

.diff-resource.removed .res-verb {
  background: #fef2f2;
  color: #dc2626;
}

.diff-resource.modified .res-verb {
  background: #fef3c7;
  color: #b45309;
}

/* 有改动待推送：紧跟在 Skill 名称右侧 */
.dirty-badge {
  flex-shrink: 0;
  padding: 1px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
  font-size: 0.7rem;
  font-weight: 500;
  line-height: 1.6;
  white-space: nowrap;
}

.msg-time {
  color: #9ca3af;
  font-size: 0.7rem;
  font-family: 'JetBrains Mono', monospace;
  min-width: 70px;
  flex-shrink: 0;
}

.msg-text {
  color: #4b5563;
  flex: 1;
}

.empty-hint {
  text-align: center;
  color: #9ca3af;
  font-size: 0.84rem;
  margin-top: 24px;
}

.hint {
  font-size: 0.84rem;
  color: #6b7280;
  margin: 0 0 16px;
}

.add-skill-list {
  list-style: none;
  padding: 0;
  margin: 0;
  max-height: 300px;
  overflow-y: auto;
}

.add-skill-list li {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  border-bottom: 1px solid #f3f4f6;
}

.add-skill-list strong {
  font-size: 0.88rem;
  font-weight: 600;
  color: #151717;
}

.add-skill-list .sub {
  display: block;
  font-size: 0.76rem;
  color: #9ca3af;
  margin-top: 2px;
}

/* 左侧文字允许收缩，右侧按钮保持横排不被挤窄换行 */
.add-skill-list li > div {
  min-width: 0;
}
.add-skill-list li .btn-sm {
  flex-shrink: 0;
  white-space: nowrap;
}

/* Shared */
.btn-sm {
  padding: 6px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  background: #ffffff;
  color: #6b7280;
  font-size: 0.82rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease, background 0.15s ease;
}

.btn-sm:hover {
  border-color: #d1d5db;
  color: #151717;
}

.btn-primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
  font-weight: 600;
}

.btn-primary:hover {
  background: #2d2f2f;
  border-color: #2d2f2f;
  color: #ffffff;
}

.btn-merge {
  background: #4f46e5;
  border-color: #4f46e5;
  color: #ffffff;
  font-weight: 600;
}

.btn-merge:hover:not(:disabled) {
  background: #4338ca;
  border-color: #4338ca;
  color: #ffffff;
}

.btn-sm:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.field {
  margin-bottom: 14px;
}

.field label {
  display: block;
  font-size: 0.82rem;
  color: #6b7280;
  margin-bottom: 6px;
}

.field input,
.field textarea,
.field select {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 9px;
  background: #f6f7f8;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.field input:focus,
.field textarea:focus,
.field select:focus {
  border-color: #151717;
  background: #ffffff;
}

.field textarea {
  min-height: 96px;
  resize: vertical;
  line-height: 1.5;
}

.check-line {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.84rem;
  color: #6b7280;
  margin-top: 6px;
}

.check-line input {
  accent-color: #151717;
}

.error-msg {
  color: #dc2626;
  font-size: 0.82rem;
  margin-top: 12px;
}

.action-banner {
  margin: 0 0 12px;
  padding: 8px 12px;
  border-radius: 10px;
  background: #eef2ff;
  border: 1px solid #e0e7ff;
  color: #4f46e5;
  font-size: 0.84rem;
  cursor: pointer;
}

</style>
