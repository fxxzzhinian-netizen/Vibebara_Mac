<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useProjectSyncStore } from '@/stores/projectSyncStore'
import {
  listNativeSkills,
  listSkillVersions,
  type NativeSkillItem,
  type SkillVersionItem,
} from '@/api/skillStore'
import { getPlatformInstalledStatus } from '@/api/orchestration'
import { useNotificationStore } from '@/stores/notificationStore'
import { useSkillSync } from '@/composables/useSkillSync'
import { promptInput } from '@/composables/useInputDialog'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { toast } from '@/composables/useToast'
import { useSlideIndicator } from '@/composables/useSlideIndicator'
import AppTopNav from '@/components/AppTopNav.vue'
import AppEmptyState from '@/components/AppEmptyState.vue'
import ProjectActivityPanel from '@/components/ProjectActivityPanel.vue'
import ProjectSkillActionIcon from '@/components/ProjectSkillActionIcon.vue'
import ProjectSkillStatusIcon from '@/components/ProjectSkillStatusIcon.vue'
import FolderPicker from '@/components/FolderPicker.vue'
import SyncStatusBadge from '@/components/SyncStatusBadge.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import SkillMergeDialog from '@/components/SkillMergeDialog.vue'
import {
  DEFAULT_PROJECT_MEMBER_PERMISSIONS,
  PROJECT_PERMISSION_KEYS,
  type ProjectPermissionKey,
  type ProjectPermissionMap,
  type ChangeItem,
  type UserSkillDeploymentInfo,
  type MergePreviewResponse,
  type MergedContent,
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
const authStore = useAuthStore()
const projectStore = useProjectSyncStore()
const notificationStore = useNotificationStore()

const projectId = computed(() => route.params.id as string)
type ProjectNavSection = 'basic' | 'skills' | 'activity' | 'management'
const activeProjectNav = ref<ProjectNavSection>('basic')
const projectNavRef = ref<HTMLElement | null>(null)
const { style: projectNavSliderStyle, ready: projectNavSliderReady } = useSlideIndicator({
  container: projectNavRef,
  activeSelector: '.project-nav-item.active',
  axis: 'y',
  trigger: () => activeProjectNav.value,
})
const projectMetrics = computed(() => {
  const project = projectStore.currentProject
  const skills = projectStore.projectSkills
  return [
    { label: '关联 Skill', value: project?.skill_count ?? skills.length },
    {
      label: '已部署',
      value: skills.filter((skill) => skill.deployment && skill.deployment.status !== 'missing').length,
    },
    { label: '待提交', value: project?.pending_commit_count ?? 0 },
    { label: '待更新', value: project?.pending_update_count ?? 0 },
    {
      label: '冲突',
      value: skills.filter((skill) => skill.deployment?.status === 'conflict').length,
    },
    {
      label: '跟踪中',
      value: skills.filter((skill) => skill.deployment?.tracking_enabled).length,
    },
  ]
})
const activeSkillStatusFilter = ref('all')
const skillStatusFilters = [
  { value: 'all', label: '全部' },
  { value: 'none', label: '未部署' },
  { value: 'synced', label: '已同步' },
  { value: 'changed', label: '待推送' },
  { value: 'outdated', label: '待更新' },
  { value: 'conflict', label: '冲突' },
  { value: 'missing', label: '路径缺失' },
  { value: 'untracked', label: '停止跟踪' },
]
const filteredProjectSkills = computed(() => {
  if (activeSkillStatusFilter.value === 'all') return projectStore.projectSkills
  return projectStore.projectSkills.filter(
    (skill) => (skill.deployment?.status || 'none') === activeSkillStatusFilter.value,
  )
})

type PermissionGroup = {
  id: string
  title: string
  description: string
  items: { key: ProjectPermissionKey; label: string; description: string }[]
}

const permissionGroups: PermissionGroup[] = [
  {
    id: 'skill-management',
    title: 'Skill 管理',
    description: '控制成员调整项目与团队 Skill 的关联关系。',
    items: [
      {
        key: 'add_skill',
        label: '关联 Skill',
        description: '允许成员将团队仓库中的 Skill 关联到当前项目。',
      },
      {
        key: 'remove_skill',
        label: '移除 Skill',
        description: '允许成员解除 Skill 与当前项目的关联。',
      },
    ],
  },
  {
    id: 'local-deployment',
    title: '本地部署',
    description: '控制成员在本机部署 Skill 及管理跟踪状态。',
    items: [
      {
        key: 'deploy_skill',
        label: '部署与重新部署',
        description: '允许成员将 Skill 部署到本机项目或全局工具目录。',
      },
      {
        key: 'manage_tracking',
        label: '管理跟踪',
        description: '允许成员停止或恢复本地 Skill 的更新跟踪。',
      },
    ],
  },
  {
    id: 'collaboration-sync',
    title: '协作同步',
    description: '控制成员在本地副本与团队仓库之间同步内容。',
    items: [
      {
        key: 'push_changes',
        label: '推送改动',
        description: '允许成员将本地改动推送到团队仓库。',
      },
      {
        key: 'pull_updates',
        label: '拉取更新',
        description: '允许成员用团队最新内容更新本地部署。',
      },
      {
        key: 'merge_conflicts',
        label: '合并冲突',
        description: '允许成员使用 AI 合并并提交冲突内容。',
      },
    ],
  },
]

const permissionLabelMap = Object.fromEntries(
  permissionGroups.flatMap((group) =>
    group.items.map((item) => [item.key, item.label]),
  ),
) as Record<ProjectPermissionKey, string>

const permissionDraft = ref<ProjectPermissionMap>({
  ...DEFAULT_PROJECT_MEMBER_PERMISSIONS,
})
const permissionEditMode = ref(false)
const permissionDraftProjectId = ref<string | null>(null)
const canManageProject = computed(
  () => projectStore.projectPermissions?.can_manage === true,
)
const permissionDirty = computed(() => {
  const configured = projectStore.projectPermissions?.member_permissions
  if (!configured) return false
  return PROJECT_PERMISSION_KEYS.some(
    (key) => permissionDraft.value[key] !== configured[key],
  )
})

watch(
  [
    () => projectStore.currentProjectId,
    () => projectStore.projectPermissions?.member_permissions,
  ],
  ([selectedProjectId, permissions]) => {
    if (
      !permissions ||
      (permissionDraftProjectId.value === selectedProjectId &&
        permissionDirty.value)
    ) {
      return
    }
    permissionDraft.value = {
      ...DEFAULT_PROJECT_MEMBER_PERMISSIONS,
      ...permissions,
    }
    permissionDraftProjectId.value = selectedProjectId ?? null
  },
  { immediate: true },
)

function canProjectOperation(key: ProjectPermissionKey): boolean {
  return projectStore.canProjectOperation(key)
}

function projectOperationTitle(
  key: ProjectPermissionKey,
  enabledTitle: string,
): string {
  if (projectStore.permissionLoading) return '正在加载项目权限'
  if (canProjectOperation(key)) return enabledTitle
  return `管理员已关闭“${permissionLabelMap[key]}”权限`
}

function guardProjectOperation(key: ProjectPermissionKey): boolean {
  if (canProjectOperation(key)) return true
  toast.warning(
    projectStore.permissionLoading
      ? '项目权限加载中，请稍后再试'
      : `管理员已关闭“${permissionLabelMap[key]}”权限`,
  )
  return false
}

function guardProjectManagement(): boolean {
  if (canManageProject.value) return true
  toast.warning('仅项目所有者或管理员可以管理项目信息')
  return false
}

async function savePermissionChanges(): Promise<boolean> {
  if (!canManageProject.value) return false
  if (!permissionDirty.value) {
    permissionEditMode.value = false
    return true
  }
  const res = await projectStore.updateProjectPermissions(
    projectId.value,
    permissionDraft.value,
  )
  if (res.success) {
    permissionEditMode.value = false
    toast.success('项目成员权限已更新')
    return true
  } else {
    toast.error(res.error || '保存项目权限失败')
    return false
  }
}

async function handlePermissionSwitchClick(event: MouseEvent, itemLabel: string) {
  if (
    canManageProject.value &&
    permissionEditMode.value &&
    !projectStore.permissionSaving
  ) {
    return
  }

  event.preventDefault()
  if (!canManageProject.value) {
    await confirmDialog({
      title: '无法编辑权限',
      message: '只有项目所有者或管理员可以修改项目成员权限。',
      confirmText: '知道了',
      cancelText: '关闭',
    })
    return
  }

  await confirmDialog({
    title: '请先进入编辑模式',
    message: `如需修改“${itemLabel}”，请先点击右上角“编辑”按钮。`,
    confirmText: '知道了',
    cancelText: '关闭',
  })
}

async function confirmPermissionSaveBeforeLeave(): Promise<boolean> {
  if (!permissionDirty.value) return true
  const shouldSave = await confirmDialog({
    title: '权限设置尚未保存',
    message: '当前权限设置已修改，请先保存后再离开。',
    confirmText: '保存并离开',
    cancelText: '继续编辑',
  })
  if (!shouldSave) return false
  return savePermissionChanges()
}

function handleBeforeUnload(event: BeforeUnloadEvent) {
  if (!permissionDirty.value) return
  event.preventDefault()
  event.returnValue = ''
}

onBeforeRouteLeave(async () => confirmPermissionSaveBeforeLeave())

const { connected } = useSkillSync(() => projectId.value, async () => {
  await loadMessageHistory()
  await refreshLocalStatuses()
})

let pollTimer: ReturnType<typeof setInterval> | undefined

const showAddSkill = ref(false)
const showEditProject = ref(false)
const editProjectName = ref('')
const editProjectDescription = ref('')
const projectSaving = ref(false)
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

onMounted(async () => {
  window.addEventListener('beforeunload', handleBeforeUnload)
  await projectStore.selectProject(projectId.value)
  await loadTeamRepoSkills()
  await loadMessageHistory()
  await refreshLocalStatuses()

  // 轮询兜底：即使 WebSocket 不可用，项目动态与本地状态也能准实时更新，无需手动刷新
  pollTimer = setInterval(async () => {
    await loadMessageHistory()
    await refreshLocalStatuses()
  }, 8000)
})

onUnmounted(() => {
  window.removeEventListener('beforeunload', handleBeforeUnload)
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
      skill_id: c.skill_id,
      deployment_id: c.deployment_id,
      user_id: c.user_id,
      user_display_name: c.user_display_name || c.user_id,
      skill_display_name: c.skill_display_name || c.skill_id,
      source: c.source,
      action: c.action,
      version: c.version,
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
  if (!guardProjectOperation('add_skill')) return
  showAddSkill.value = true
  loadTeamRepoSkills()
}

function openEditProject() {
  if (!guardProjectManagement()) return
  if (activeProjectNav.value === 'management') {
    if (!projectStore.projectPermissions || projectStore.permissionLoading) {
      toast.warning('项目权限仍在加载，请稍后再试')
      return
    }
    permissionEditMode.value = true
    return
  }
  editProjectName.value = projectStore.currentProject?.name || ''
  editProjectDescription.value = projectStore.currentProject?.description || ''
  showEditProject.value = true
}

async function submitEditProject() {
  if (!guardProjectManagement()) return
  const name = editProjectName.value.trim()
  if (!name) {
    toast.warning('请输入项目名称')
    return
  }

  projectSaving.value = true
  const res = await projectStore.update(
    projectId.value,
    name,
    editProjectDescription.value.trim(),
  )
  projectSaving.value = false

  if (!res.success) {
    toast.error(res.error || '保存失败')
    return
  }

  showEditProject.value = false
  toast.success('项目已更新')
}

async function deleteCurrentProject() {
  if (!guardProjectManagement()) return
  const projectName = projectStore.currentProject?.name || '当前项目'
  const ok = await confirmDialog({
    title: '删除项目',
    message: `确认删除项目「${projectName}」？项目关联关系与部署记录将一并删除，且不可恢复。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return

  const res = await projectStore.remove(projectId.value)
  if (!res.success) {
    toast.error(res.error || '删除失败')
    return
  }

  toast.success('项目已删除')
  router.push('/team/projects')
}

const availableSkills = computed(() => {
  const linked = new Set(projectStore.projectSkills.map((s) => s.skill_id))
  return teamRepoSkills.value.filter((s) => !linked.has(s.id))
})

async function addSkillToProject(skillId: string) {
  if (!guardProjectOperation('add_skill')) return
  const res = await projectStore.addSkill(projectId.value, skillId)
  if (!res.success) {
    toast.error(res.error || '添加失败')
  } else {
    showAddSkill.value = false
    toast.success('已添加 Skill 到项目')
    await loadMessageHistory()
  }
}

async function removeSkill(skillId: string) {
  if (!guardProjectOperation('remove_skill')) return
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
    await loadMessageHistory()
  }
}

function openDeploy(skillId: string) {
  if (!guardProjectOperation('deploy_skill')) return
  deploySkillId.value = skillId
  deployTool.value = 'cursor'
  deployPath.value = ''
  deployOverwrite.value = false
  deployToGlobal.value = false
  showDeployModal.value = true
}

async function submitDeploy() {
  if (!guardProjectOperation('deploy_skill')) return
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
  await loadMessageHistory()
  await promptOpenAfterDeploy(openedTool, openedPath)
}

async function stopTracking(deploymentId: string) {
  if (!guardProjectOperation('manage_tracking')) return
  const res = await projectStore.stopTracking(deploymentId)
  if (!res.success) {
    toast.error(res.error || '停止跟踪失败')
    return
  }
  toast.success('已停止跟踪')
  await loadMessageHistory()
}

async function resumeTracking(deploymentId: string) {
  if (!guardProjectOperation('manage_tracking')) return
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
  await loadMessageHistory()
  await refreshLocalStatuses()
}

async function pushDeploy(deploymentId: string) {
  if (!guardProjectOperation('push_changes')) return
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
  if (!guardProjectOperation('pull_updates')) return
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
  if (!guardProjectOperation('merge_conflicts')) return
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
  if (!guardProjectOperation('merge_conflicts')) return
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
  if (!canProjectOperation('deploy_skill')) return
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

function statusTagLabel(status?: string): string {
  const labels: Record<string, string> = {
    synced: 'Skill 已同步',
    changed: '本地改动待推送',
    outdated: '团队版本待更新',
    conflict: 'Skill 存在冲突',
    missing: '部署路径缺失',
    untracked: 'Skill 已停止跟踪',
  }
  return labels[status || ''] || 'Skill 未部署'
}

function formatTime(ts: string): string {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts.slice(11, 19) || ''
  return d.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatProjectDate(ts: string | null | undefined): string {
  if (!ts) return '--'
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ts
  return d.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function goBack() {
  router.push('/team/projects')
}

async function selectProjectSection(section: ProjectNavSection) {
  if (section === activeProjectNav.value) return
  if (!(await confirmPermissionSaveBeforeLeave())) return
  if (activeProjectNav.value === 'management') {
    permissionEditMode.value = false
  }
  activeProjectNav.value = section
}
</script>

<template>
  <div class="project-page">
    <AppTopNav />

    <div class="content">
      <div class="project-layout">
        <aside class="project-sidebar" aria-label="项目导航">
          <nav ref="projectNavRef" class="project-nav">
            <span
              class="project-nav-slider"
              :class="{ ready: projectNavSliderReady }"
              :style="projectNavSliderStyle"
            ></span>
            <button
              class="project-nav-item"
              :class="{ active: activeProjectNav === 'basic' }"
              @click="selectProjectSection('basic')"
            >
              项目信息
            </button>
            <button
              class="project-nav-item"
              :class="{ active: activeProjectNav === 'skills' }"
              @click="selectProjectSection('skills')"
            >
              项目 SKILL
            </button>
            <button
              class="project-nav-item"
              :class="{ active: activeProjectNav === 'activity' }"
              @click="selectProjectSection('activity')"
            >
              项目动态
            </button>
            <button
              class="project-nav-item"
              :class="{ active: activeProjectNav === 'management' }"
              @click="selectProjectSection('management')"
            >
              项目管理
            </button>
          </nav>
        </aside>

        <main class="project-workspace">
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
        <div
          class="toolbar-right action-menu"
          :class="{ 'manager-actions': canManageProject }"
          aria-label="项目操作"
        >
          <button
            v-if="canManageProject"
            class="project-action-btn save"
            :disabled="!permissionDirty || projectStore.permissionSaving"
            :title="
              projectStore.permissionSaving
                ? '保存中…'
                : permissionDirty
                  ? '保存项目配置'
                  : '暂无未保存配置'
            "
            :aria-label="projectStore.permissionSaving ? '保存中' : '保存项目配置'"
            @click="savePermissionChanges"
          >
            <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path
                fill="currentColor"
                d="M518.528 709.973333l121.258667-122.453333a32 32 0 0 0-0.426667-45.226667 31.146667 31.146667 0 0 0-44.373333 0l-67.157334 68.266667V404.906667a31.445333 31.445333 0 1 0-62.933333 0v205.653333l-67.157333-68.266667a31.146667 31.146667 0 0 0-44.373334 0 32.426667 32.426667 0 0 0 0 45.226667l120.832 122.453333a32.768 32.768 0 0 0 22.4 9.386667 32.725333 32.725333 0 0 0 21.973334-9.386667z m306.133333-324.864c9.941333-0.128 20.736-0.256 30.592-0.256 10.965333 0 19.413333 8.533333 19.413334 19.2v343.04c0 105.813333-85.333333 191.573333-190.08 191.573334H348.714667C238.506667 938.666667 149.333333 848.64 149.333333 737.706667V277.76C149.333333 171.946667 234.24 85.333333 339.84 85.333333h225.578667c10.581333 0 19.456 8.96 19.456 19.626667v137.386667c0 78.08 63.36 142.08 141.098666 142.506666 17.834667 0 33.834667 0.128 47.786667 0.256 10.794667 0.085333 20.352 0.170667 28.672 0.170667 5.973333 0 13.824-0.085333 22.229333-0.170667z m11.818667-62.293333c-34.688 0.128-75.648 0-105.088-0.298667-46.72 0-85.205333-38.826667-85.205333-86.058666V123.989333c0-18.346667 22.101333-27.52 34.688-14.250666l124.416 130.645333 45.696 48a20.352 20.352 0 0 1-14.506667 34.432z"
              />
            </svg>
          </button>
          <button
            class="project-action-btn link-skill"
            :disabled="!canProjectOperation('add_skill')"
            :title="projectOperationTitle('add_skill', '关联 Skill')"
            aria-label="关联 Skill"
            @click="openAddSkill"
          >
            <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M312.746667 85.333333h398.08C855.893333 85.333333 938.666667 167.253333 938.666667 312.746667v398.506666c0 144.64-82.346667 227.413333-227.413334 227.413334H312.746667C167.253333 938.666667 85.333333 855.893333 85.333333 711.253333V312.746667C85.333333 167.253333 167.253333 85.333333 312.746667 85.333333z m234.24 462.08h121.173333c19.626667-0.426667 35.413333-16.213333 35.413333-35.84 0-19.626667-15.786667-35.413333-35.413333-35.413333h-121.173333V355.84c0-19.626667-15.786667-35.413333-35.413334-35.413333-19.626667 0-35.413333 15.786667-35.413333 35.413333v120.32H355.413333c-9.386667 0-18.346667 3.84-25.173333 10.24a36.949333 36.949333 0 0 0-10.24 25.173333c0 19.626667 15.786667 35.413333 35.413333 35.84h120.746667v120.746667c0 19.626667 15.786667 35.413333 35.413333 35.413333 19.626667 0 35.413333-15.786667 35.413334-35.413333v-120.746667z" fill="currentColor"></path>
            </svg>
          </button>
          <button
            v-if="canManageProject"
            class="project-action-btn danger"
            title="删除"
            aria-label="删除"
            @click="deleteCurrentProject"
          >
            <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M865.578667 223.701333c16.64 0 30.421333 13.781333 30.421333 31.317334v16.213333a31.146667 31.146667 0 0 1-30.421333 31.317333H158.464A31.146667 31.146667 0 0 1 128 271.232v-16.213333c0-17.536 13.824-31.317333 30.464-31.317334H282.88c25.258667 0 47.232-17.962667 52.906667-43.306666l6.528-29.098667C352.469333 111.658667 385.749333 85.333333 423.893333 85.333333h176.213334c37.717333 0 71.424 26.325333 81.152 63.872l6.954666 31.146667a54.613333 54.613333 0 0 0 52.949334 43.349333h124.416z m-63.189334 592.682667c12.970667-121.045333 35.712-408.618667 35.712-411.52a31.829333 31.829333 0 0 0-7.68-23.808 30.976 30.976 0 0 0-22.357333-9.984H216.32c-8.533333 0-16.682667 3.712-22.357333 9.984a33.706667 33.706667 0 0 0-8.106667 23.808l2.261333 27.605333c6.058667 75.221333 22.912 284.757333 33.834667 383.914667 7.68 73.045333 55.637333 118.954667 125.056 120.618667 53.589333 1.237333 108.8 1.664 165.205333 1.664 53.162667 0 107.093333-0.426667 162.346667-1.664 71.850667-1.237333 119.722667-46.336 127.872-120.618667z" fill="currentColor"></path>
            </svg>
          </button>
          <button
            v-if="canManageProject"
            class="project-action-btn edit"
            :class="{
              'permission-editing':
                activeProjectNav === 'management' && permissionEditMode,
            }"
            :title="
              activeProjectNav === 'management'
                ? permissionEditMode
                  ? '权限编辑中'
                  : '编辑项目权限'
                : '编辑项目信息'
            "
            :aria-label="
              activeProjectNav === 'management'
                ? permissionEditMode
                  ? '权限编辑中'
                  : '编辑项目权限'
                : '编辑项目信息'
            "
            @click="openEditProject"
          >
            <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
              <path d="M400.042667 854.528l374.912-484.821333c20.352-26.112 27.605333-56.32 20.821333-87.125334-5.888-27.989333-23.082667-54.613333-48.896-74.752L683.946667 157.824c-54.784-43.562667-122.709333-38.997333-161.664 11.008l-42.069334 54.613333a16.128 16.128 0 0 0 2.688 22.442667l108.672 87.125333c7.253333 6.912 12.672 16.085333 14.08 27.093334a40.32 40.32 0 0 1-34.901333 44.458666 36.096 36.096 0 0 1-27.605333-7.765333l-111.829334-89.002667a13.354667 13.354667 0 0 0-18.133333 2.304L147.413333 654.08c-17.194667 21.546667-23.082667 49.536-17.194666 76.586667l33.962666 147.242666a17.066667 17.066667 0 0 0 16.725334 13.312l149.418666-1.834666a89.770667 89.770667 0 0 0 69.717334-34.858667z m209.237333-45.866667h243.626667c23.765333 0 43.093333 19.626667 43.093333 43.690667 0 24.106667-19.328 43.648-43.093333 43.648h-243.626667c-23.765333 0-43.093333-19.541333-43.093333-43.648s19.328-43.690667 43.093333-43.690667z" fill="currentColor"></path>
            </svg>
          </button>
        </div>
      </div>

      <div v-show="activeProjectNav === 'basic'" class="project-info project-route-panel">
        <div class="project-metrics">
          <div v-for="metric in projectMetrics" :key="metric.label" class="project-metric">
            <strong>{{ metric.value }}</strong>
            <span>{{ metric.label }}</span>
          </div>
        </div>

        <div class="project-detail-form">
          <div class="project-detail-field">
            <span class="project-detail-label">名称</span>
            <div class="project-detail-input">
              {{ projectStore.currentProject?.name || '--' }}
            </div>
          </div>
          <div class="project-detail-field">
            <span class="project-detail-label">描述</span>
            <div class="project-detail-textarea">
              {{ projectStore.currentProject?.description || '暂无描述' }}
            </div>
          </div>
          <div class="project-detail-meta">
            <span>创建者&nbsp; {{ projectStore.currentProject?.created_by || '--' }}</span>
            <span>创建&nbsp; {{ formatProjectDate(projectStore.currentProject?.created_at) }}</span>
            <span>更新&nbsp; {{ formatProjectDate(projectStore.currentProject?.updated_at) }}</span>
            <span>最近提交&nbsp; {{ formatProjectDate(projectStore.currentProject?.last_commit_at) }}</span>
          </div>
        </div>
      </div>

      <div v-show="activeProjectNav !== 'basic'" class="project-main">
        <section v-show="activeProjectNav === 'skills'" class="project-route-panel">
        <!-- Skill 列表 -->
        <div class="skill-toolbar">
          <div class="skill-filters" aria-label="按 Skill 状态筛选">
            <button
              v-for="filter in skillStatusFilters"
              :key="filter.value"
              :class="{ active: activeSkillStatusFilter === filter.value }"
              @click="activeSkillStatusFilter = filter.value"
            >
              {{ filter.label }}
            </button>
          </div>
        </div>

        <div class="skill-list">
          <article
            v-for="skill in filteredProjectSkills"
            :key="skill.skill_id"
            class="skill-card"
            role="link"
            tabindex="0"
            @click="router.push('/skills/' + skill.skill_id)"
            @keydown.enter="router.push('/skills/' + skill.skill_id)"
          >
            <div class="skill-card-head">
              <span
                class="skill-status"
                :class="`status-${skill.deployment?.status || 'none'}`"
                :title="statusLabel(skill.deployment?.status)"
              >
                <ProjectSkillStatusIcon :status="skill.deployment?.status" />
              </span>
              <div class="skill-title-block">
                <h4 class="skill-name">{{ skill.display_name || skill.skill_id }}</h4>
                <span
                  class="skill-state-tag"
                  :class="`status-${skill.deployment?.status || 'none'}`"
                >
                  {{ statusTagLabel(skill.deployment?.status) }}
                </span>
              </div>
            </div>
            <p :title="skill.description || ''">{{ skill.description || '暂无描述' }}</p>
            <div class="skill-card-actions" @click.stop>
              <button
                v-if="!skill.deployment"
                :disabled="!canProjectOperation('deploy_skill')"
                :title="projectOperationTitle('deploy_skill', '部署到本机项目')"
                @click="openDeploy(skill.skill_id)"
              >
                <ProjectSkillActionIcon action="deploy" />
                部署
              </button>
              <button
                v-if="skill.deployment?.tracking_enabled && skill.deployment.status !== 'conflict' && hasLocalChanges(skill.deployment)"
                :disabled="pushingId === skill.deployment.id || !canProjectOperation('push_changes')"
                :title="projectOperationTitle('push_changes', '推送本地改动到团队仓库')"
                @click="pushDeploy(skill.deployment.id)"
              >
                <ProjectSkillActionIcon action="push" />
                {{ pushingId === skill.deployment.id ? '推送中' : '推送' }}
              </button>
              <button
                v-if="skill.deployment?.status === 'conflict'"
                :disabled="mergingId === skill.deployment.id || !canProjectOperation('merge_conflicts')"
                :title="projectOperationTitle('merge_conflicts', '使用 AI 合并冲突')"
                @click="openMerge(skill.deployment)"
              >
                <ProjectSkillActionIcon action="merge" />
                {{ mergingId === skill.deployment.id ? '分析中' : 'AI 合并' }}
              </button>
              <button
                v-if="skill.deployment && ['outdated', 'conflict'].includes(skill.deployment.status)"
                :disabled="pullingId === skill.deployment.id || !canProjectOperation('pull_updates')"
                :title="projectOperationTitle('pull_updates', '拉取团队最新内容')"
                @click="pullUpdate(skill.deployment.id, skill.deployment.status)"
              >
                <ProjectSkillActionIcon action="pull" />
                {{ pullingId === skill.deployment.id ? '更新中' : '更新本地' }}
              </button>
              <button
                v-if="skill.deployment && !skill.deployment.tracking_enabled && skill.deployment.status !== 'missing' && !redeployHintIds[skill.deployment.id]"
                :disabled="!canProjectOperation('manage_tracking')"
                :title="projectOperationTitle('manage_tracking', '恢复本地更新跟踪')"
                @click="resumeTracking(skill.deployment.id)"
              >
                <ProjectSkillActionIcon action="resume" />
                恢复跟踪
              </button>
              <button
                v-if="skill.deployment && (skill.deployment.status === 'missing' || redeployHintIds[skill.deployment.id])"
                :disabled="!canProjectOperation('deploy_skill')"
                :title="projectOperationTitle('deploy_skill', '重新部署到本机项目')"
                @click="openDeploy(skill.skill_id)"
              >
                <ProjectSkillActionIcon action="redeploy" />
                重新部署
              </button>
              <button
                v-if="skill.deployment?.tracking_enabled && skill.deployment.status === 'synced'"
                :disabled="!canProjectOperation('manage_tracking')"
                :title="projectOperationTitle('manage_tracking', '停止本地更新跟踪')"
                @click="stopTracking(skill.deployment.id)"
              >
                <ProjectSkillActionIcon action="stop" />
                停止跟踪
              </button>
              <button
                class="danger"
                :disabled="!canProjectOperation('remove_skill')"
                :title="projectOperationTitle('remove_skill', '从项目中移除 Skill')"
                @click="removeSkill(skill.skill_id)"
              >
                <ProjectSkillActionIcon action="remove" />
                移除
              </button>
            </div>
          </article>
        </div>

        <div
          v-if="projectStore.projectSkills.length > 0 && filteredProjectSkills.length === 0"
          class="skill-filter-empty"
        >
          当前状态下暂无 Skill
        </div>

        <AppEmptyState
          v-if="projectStore.projectSkills.length === 0"
          compact
          title="暂无 Skill"
          description="点击右上角关联 Skill，将团队 Skill 添加到项目"
        />
        </section>

        <section v-show="activeProjectNav === 'activity'" class="project-route-panel">
        <ProjectActivityPanel
          :project="projectStore.currentProject"
          :skills="projectStore.projectSkills"
          :messages="notificationStore.messages"
          :current-user-id="authStore.user?.id"
          @detail="openDetail"
        />
        </section>

        <section
          v-show="activeProjectNav === 'management'"
          class="project-route-panel permission-management"
        >
          <div
            v-if="projectStore.permissionLoading && !projectStore.projectPermissions"
            class="permission-state-card permission-loading"
            role="status"
          >
              <span class="permission-spinner" aria-hidden="true"></span>
              正在加载项目权限…
          </div>

          <div
            v-else-if="projectStore.permissionError"
            class="permission-state-card permission-error"
            role="alert"
          >
            <span>{{ projectStore.permissionError }}</span>
            <button
              v-if="!projectStore.permissionSaving"
              type="button"
              @click="projectStore.fetchProjectPermissions(projectId)"
            >
              重试
            </button>
          </div>

          <template v-else-if="projectStore.projectPermissions">
            <div class="permission-groups">
              <section
                v-for="group in permissionGroups"
                :key="group.id"
                class="permission-group"
              >
                <div class="permission-group-heading">
                  <strong>{{ group.title }}</strong>
                </div>
                <div class="permission-category-card">
                  <div class="permission-rows">
                    <div
                      v-for="item in group.items"
                      :key="item.key"
                      class="permission-row"
                    >
                      <div class="permission-copy">
                        <strong>{{ item.label }}</strong>
                        <span>{{ item.description }}</span>
                      </div>
                      <label
                        class="permission-switch"
                        :class="{
                          disabled:
                            !canManageProject ||
                            !permissionEditMode ||
                            projectStore.permissionSaving,
                        }"
                        :title="
                          !canManageProject
                            ? '只有项目所有者或管理员可以修改成员权限'
                            : !permissionEditMode
                              ? '请先点击右上角“编辑”按钮'
                              : `允许成员${item.label}`
                        "
                        @click="handlePermissionSwitchClick($event, item.label)"
                      >
                        <input
                          v-model="permissionDraft[item.key]"
                          type="checkbox"
                          :disabled="
                            !canManageProject ||
                            !permissionEditMode ||
                            projectStore.permissionSaving
                          "
                          :aria-label="`允许成员${item.label}`"
                        />
                        <span class="permission-switch-track" aria-hidden="true">
                          <span class="permission-switch-thumb"></span>
                        </span>
                      </label>
                    </div>
                  </div>
                </div>
              </section>
            </div>
          </template>
        </section>
      </div>
        </main>
      </div>
    </div>

    <BaseModal v-model="showEditProject" title="编辑项目">
      <div class="field">
        <label>项目名称</label>
        <input v-model="editProjectName" maxlength="100" placeholder="请输入项目名称" />
      </div>
      <div class="field">
        <label>项目描述</label>
        <textarea
          v-model="editProjectDescription"
          rows="5"
          placeholder="请输入项目描述"
        ></textarea>
      </div>
      <template #footer>
        <button class="btn-sm" :disabled="projectSaving" @click="showEditProject = false">
          取消
        </button>
        <button class="btn-sm btn-primary" :disabled="projectSaving" @click="submitEditProject">
          {{ projectSaving ? '保存中...' : '保存' }}
        </button>
      </template>
    </BaseModal>

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
          <button
            class="btn-sm btn-primary"
            :disabled="!canProjectOperation('add_skill')"
            :title="projectOperationTitle('add_skill', '添加到当前项目')"
            @click="addSkillToProject(skill.id)"
          >
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
        <button
          class="btn-sm btn-primary"
          :disabled="deployLoading || !canProjectOperation('deploy_skill')"
          :title="projectOperationTitle('deploy_skill', '部署 Skill')"
          @click="submitDeploy"
        >
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
  margin-bottom: 1.75rem;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.toolbar-right {
  display: flex;
  align-items: center;
}

.toolbar-right.action-menu {
  position: relative;
  width: 296px;
  height: 58px;
  padding: 4px 8px;
  gap: 0;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  box-sizing: border-box;
  border-radius: 12px;
  background: #f1f3f5;
  transition: width 0.2s ease-in;
}

.toolbar-right.action-menu:hover,
.toolbar-right.action-menu:focus-within {
  width: 328px;
}

.toolbar-right.action-menu:has(.project-action-btn.link-skill:hover),
.toolbar-right.action-menu:has(.project-action-btn.link-skill:focus-visible) {
  width: 358px;
}

.action-menu .project-action-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 70px;
  min-width: 0;
  height: 44px;
  margin: 0;
  padding: 0;
  overflow: hidden;
  border: 0;
  border-radius: 8px;
  background: transparent;
  font: inherit;
  line-height: 1;
  cursor: pointer;
  -webkit-tap-highlight-color: transparent;
  transform-origin: center left;
  transition: width 0.2s ease-in, background-color 0.2s ease-in, color 0.2s ease-in;
}

.action-menu:hover .project-action-btn:hover,
.action-menu .project-action-btn:focus-visible {
  width: 102px;
}

.action-menu:hover .project-action-btn.link-skill:hover,
.action-menu .project-action-btn.link-skill:focus-visible {
  width: 132px;
}

.action-menu .project-action-btn:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 2px;
}

.action-menu .project-action-btn::before {
  position: absolute;
  top: 50%;
  right: 8px;
  left: 48px;
  color: currentColor;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-align: center;
  white-space: nowrap;
  opacity: 0;
  transform: translate(100%, -50%);
  transition: transform 0.2s ease-in, opacity 0.2s ease-in;
}

.action-menu .project-action-btn.link-skill::before {
  content: '关联 Skill';
  right: 11px;
  left: 51px;
  letter-spacing: 0;
}

.action-menu .project-action-btn.save::before {
  content: '保存';
  letter-spacing: 0.18em;
}

.action-menu .project-action-btn.danger::before {
  content: '删除';
  letter-spacing: 0.18em;
}

.action-menu .project-action-btn.edit::before {
  content: '编辑';
  letter-spacing: 0.18em;
}

.action-menu:hover .project-action-btn:hover::before,
.action-menu .project-action-btn:focus-visible::before {
  opacity: 1;
  transform: translate(0, -50%);
}

.action-menu .project-action-btn svg {
  position: absolute;
  left: 21px;
  width: 28px;
  height: 28px;
  display: block;
  flex-shrink: 0;
  transition: left 0.2s ease-in;
}

.action-menu:hover .project-action-btn.link-skill:hover svg,
.action-menu .project-action-btn.link-skill:focus-visible svg {
  left: 14px;
}

.action-menu .project-action-btn.link-skill {
  color: #4f46e5;
}

.action-menu .project-action-btn.link-skill:hover,
.action-menu .project-action-btn.link-skill:focus-visible {
  background: #e8e7ff;
}

.action-menu .project-action-btn.save {
  color: #0284c7;
}

.action-menu .project-action-btn.save:hover,
.action-menu .project-action-btn.save:focus-visible {
  background: #dbeefe;
}

.action-menu .project-action-btn.danger {
  color: #dc2626;
}

.action-menu .project-action-btn.danger:hover,
.action-menu .project-action-btn.danger:focus-visible {
  background: #fee2e2;
}

.action-menu .project-action-btn.edit {
  color: #151717;
}

.action-menu .project-action-btn.edit:hover,
.action-menu .project-action-btn.edit:focus-visible {
  background: #e2e5e9;
}

.action-menu .project-action-btn.edit.permission-editing {
  background: #d9dde2;
}

.toolbar-right.action-menu:not(.manager-actions) {
  width: 86px;
}

.toolbar-right.action-menu:not(.manager-actions):hover,
.toolbar-right.action-menu:not(.manager-actions):focus-within,
.toolbar-right.action-menu:not(.manager-actions):has(.project-action-btn.link-skill:hover),
.toolbar-right.action-menu:not(.manager-actions):has(.project-action-btn.link-skill:focus-visible) {
  width: 148px;
}

.action-menu .project-action-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.action-menu .project-action-btn:disabled:hover {
  background: transparent;
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
  padding: 2.75rem 24px 2rem;
}

.project-layout {
  width: 100%;
  margin: 0;
  display: grid;
  grid-template-columns: 176px minmax(0, 1fr);
  column-gap: 1.25rem;
  align-items: start;
}

.project-sidebar {
  grid-column: 1;
  grid-row: 1;
  align-self: stretch;
  min-height: calc(100vh - 176px);
  margin-top: 66px;
  padding: 0.5rem;
  box-sizing: border-box;
  background: #eef0f3;
  border: 1px solid #ebedf0;
  border-radius: 14px;
}

.project-nav {
  position: sticky;
  top: 92px;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.project-nav button {
  position: relative;
  z-index: 1;
  display: block;
  width: 100%;
  padding: 0.72rem 0.8rem;
  border: 0;
  border-radius: 9px;
  background: transparent;
  color: #6b7280;
  font: inherit;
  font-size: 0.95rem;
  font-weight: 500;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.project-nav-slider {
  position: absolute;
  z-index: 0;
  top: 0;
  right: 0;
  left: 0;
  height: 0;
  border-radius: 9px;
  background: #151717;
  opacity: 0;
  pointer-events: none;
  will-change: transform, height;
}

.project-nav-slider.ready {
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
    height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
}

.project-nav button:hover:not(.active) {
  background: #e3e6eb;
  color: #151717;
}

.project-nav button.active {
  color: #ffffff;
  font-weight: 600;
}

.project-nav button:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 3px;
}

.project-workspace {
  grid-column: 2;
  grid-row: 1;
  display: block;
  width: 100%;
  min-width: 0;
}

.toolbar {
  width: calc(100% + 196px);
  margin-left: -196px;
}

.toolbar-left {
  margin-left: 0.5rem;
}

.project-info {
  width: 100%;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.toolbar {
  scroll-margin-top: 92px;
}

.project-main {
  width: 100%;
  min-width: 0;
}

.project-metrics {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  min-height: 96px;
  padding: 12px 10px;
  box-sizing: border-box;
  background: #eef0f3;
  border: 1px solid #ebedf0;
  border-radius: 14px;
}

.project-metric {
  position: relative;
  min-width: 0;
  margin: 0 14px;
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  border-radius: 10px;
  text-align: center;
  transition: background 0.15s ease;
}

.project-metric:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 0;
  right: -14px;
  bottom: 0;
  width: 2px;
  background: #d6dae0;
}

.project-metric:hover,
.project-metric:active {
  background: #8b929b;
  box-shadow: none;
}

.project-metric strong {
  color: #1f2328;
  font-size: 1.65rem;
  font-weight: 700;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.project-metric span {
  color: #8b929b;
  font-size: 0.8rem;
  line-height: 1.3;
  white-space: nowrap;
}

.project-metric:hover strong,
.project-metric:hover span,
.project-metric:active strong,
.project-metric:active span {
  color: #ffffff;
}

.project-detail-form {
  width: 100%;
}

.project-detail-field + .project-detail-field {
  margin-top: 14px;
}

.project-detail-label {
  display: block;
  margin-bottom: 6px;
  color: #606873;
  font-size: 0.78rem;
  font-weight: 500;
}

.project-detail-input,
.project-detail-textarea {
  box-sizing: border-box;
  width: 100%;
  background: #eef0f3;
  border: 1px solid transparent;
  border-radius: 7px;
  color: #4b5563;
  font-size: 0.86rem;
}

.project-detail-input {
  min-height: 40px;
  padding: 10px 12px;
}

.project-detail-textarea {
  min-height: 250px;
  padding: 12px;
  line-height: 1.65;
}

.project-detail-meta {
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  margin-top: 18px;
  color: #8b929b;
  font-size: 0.72rem;
}

.permission-management {
  max-width: none;
  margin: -12px 0 0;
  padding-bottom: 20px;
}

.permission-state-card,
.permission-category-card {
  box-sizing: border-box;
  border: 0;
  border-radius: 8px;
  background: #f0f1f2;
  box-shadow: none;
}

.permission-state-card {
  min-height: 132px;
  padding: 18px 24px;
}

.permission-category-card {
  padding: 10px 24px;
}

.permission-error button {
  min-height: 32px;
  padding: 6px 11px;
  border: 1px solid #b8bec7;
  border-radius: 4px;
  background: #ffffff;
  color: #333842;
  font: inherit;
  font-size: 0.76rem;
  font-weight: 600;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.permission-error button:hover {
  border-color: #737983;
  background: #f0f1f3;
  color: #1f2329;
}

.permission-error button:focus-visible {
  outline: 2px solid #1f75cb;
  outline-offset: 2px;
}

.permission-loading {
  min-height: 132px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #7b838e;
  font-size: 0.84rem;
}

.permission-spinner {
  width: 16px;
  height: 16px;
  box-sizing: border-box;
  border: 2px solid #d4d9df;
  border-top-color: #151717;
  border-radius: 50%;
  animation: permission-spin 0.75s linear infinite;
}

@keyframes permission-spin {
  to {
    transform: rotate(360deg);
  }
}

.permission-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 10px 12px;
  border-left: 3px solid #dc2626;
  background: #fff5f5;
  color: #b42318;
  font-size: 0.8rem;
}

.permission-error button {
  flex: none;
  border-color: #f1c6c3;
  color: #b42318;
}

.permission-groups {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.permission-group {
  min-width: 0;
}

.permission-group-heading {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 3px;
  margin: 0 0 9px 2px;
}

.permission-group-heading strong {
  color: #1f2329;
  font-size: 1.05rem;
  font-weight: 700;
}

.permission-rows {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.permission-row {
  min-height: 68px;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 14px;
}

.permission-copy {
  min-width: 0;
  display: flex;
  align-items: flex-start;
  flex-direction: column;
  gap: 4px;
}

.permission-copy strong {
  overflow: hidden;
  color: #4f5660;
  font-size: 0.92rem;
  font-weight: 600;
  line-height: 1.35;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.permission-copy span {
  color: #8b929b;
  font-size: 0.82rem;
  line-height: 1.45;
}

.permission-switch {
  position: relative;
  flex: none;
  display: inline-flex;
  align-items: center;
  cursor: pointer;
}

.permission-switch.disabled {
  cursor: not-allowed;
}

.permission-switch input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.permission-switch-track {
  width: 40px;
  height: 22px;
  padding: 2px;
  box-sizing: border-box;
  display: block;
  border: 1px solid #cdd1d6;
  border-radius: 999px;
  background: #d8dadd;
  transition: border-color 0.16s ease, background 0.16s ease;
}

.permission-switch-thumb {
  display: block;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(21, 23, 23, 0.24);
  transition: transform 0.16s ease;
}

.permission-switch input:checked + .permission-switch-track {
  border-color: #343638;
  background: #343638;
}

.permission-switch input:checked + .permission-switch-track .permission-switch-thumb {
  transform: translateX(18px);
}

.permission-switch input:focus-visible + .permission-switch-track {
  outline: 2px solid #343638;
  outline-offset: 3px;
}

.permission-switch input:disabled + .permission-switch-track {
  opacity: 0.62;
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

.skill-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.skill-filters {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.skill-filters button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-height: 40px;
  padding: 8px 17px;
  border: 0;
  border-radius: 10px;
  background: transparent;
  color: #6b7280;
  font: inherit;
  font-size: 0.9rem;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.skill-filters button:hover:not(.active) {
  background: #f6f7f8;
  color: #151717;
}

.skill-filters button.active {
  background: #eef0f3;
  color: #151717;
  font-weight: 700;
}

.skill-toolbar > .btn-sm {
  flex: none;
}

.skill-filter-empty {
  padding: 54px 20px;
  color: #9ca3af;
  font-size: 0.84rem;
  text-align: center;
}

.skill-list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 18px;
}

.skill-card {
  position: relative;
  min-height: 150px;
  box-sizing: border-box;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border: 2px solid #151717;
  border-radius: 18px;
  padding: 20px 22px;
  overflow: hidden;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.skill-card:hover {
  border-color: #151717;
  box-shadow: 0 6px 18px rgba(21, 23, 23, 0.07);
}

.skill-card:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 3px;
}

.skill-status {
  flex: none;
  width: 52px;
  height: 52px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  --status-bg: #dbe7ff;
  position: relative;
  background: #ffffff;
  color: #8b929b;
  border: 4px solid #ffffff;
  outline: 2px solid #151717;
  box-sizing: border-box;
}

.skill-status::before {
  content: '';
  position: absolute;
  inset: 1.5px;
  border-radius: 50%;
  background: var(--status-bg);
}

.skill-status svg {
  width: 34px;
  height: 34px;
  display: block;
  position: relative;
  z-index: 1;
}

.skill-status.status-synced {
  --status-bg: #d4f2df;
  color: #168a4a;
}

.skill-status.status-changed {
  --status-bg: #ffe8b5;
  color: #c27713;
}

.skill-status.status-outdated {
  --status-bg: #e2dbff;
  color: #6d5bd0;
}

.skill-status.status-conflict,
.skill-status.status-missing {
  --status-bg: #ffd8dc;
  color: #d9363e;
}

.skill-status.status-untracked {
  --status-bg: #dce2e8;
  color: #727b86;
}

.skill-card-head {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
}

.skill-title-block {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.skill-card-head h4 {
  margin: 0;
  min-width: 0;
  font-size: 1.08rem;
  font-weight: 600;
  color: #151717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.skill-card-head h4.skill-name {
  cursor: inherit;
}

.skill-state-tag {
  color: #8b929b;
  font-size: 0.76rem;
  font-weight: 500;
  line-height: 1.35;
}

.skill-state-tag.status-synced {
  color: #168a4a;
}

.skill-state-tag.status-changed {
  color: #b66a08;
}

.skill-state-tag.status-outdated {
  color: #6652c7;
}

.skill-state-tag.status-conflict,
.skill-state-tag.status-missing {
  color: #d9363e;
}

.skill-state-tag.status-untracked {
  color: #727b86;
}

.skill-card > p {
  margin: 14px 0 0;
  font-size: 0.9rem;
  line-height: 1.65;
  color: #6b7280;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  overflow: hidden;
}

.skill-card-actions {
  position: absolute;
  z-index: 3;
  right: 0;
  bottom: 0;
  left: 0;
  height: 68px;
  box-sizing: border-box;
  padding: 12px 16px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  flex-wrap: wrap;
  border-radius: 0 0 15px 15px;
  border-top: 0;
  background: rgba(255, 255, 255, 0.86);
  box-shadow: none;
  backdrop-filter: blur(14px) saturate(1.25);
  -webkit-backdrop-filter: blur(14px) saturate(1.25);
  opacity: 0;
  pointer-events: none;
  transform: translateY(102%);
  transition: transform 0.2s ease, opacity 0.16s ease;
}

.skill-card-actions::before {
  content: '';
  position: absolute;
  right: 0;
  bottom: 100%;
  left: 0;
  height: 8px;
  pointer-events: none;
  background: linear-gradient(
    to bottom,
    rgba(255, 255, 255, 0) 0%,
    rgba(255, 255, 255, 0.52) 48%,
    rgba(255, 255, 255, 0.86) 100%
  );
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.skill-card:hover .skill-card-actions,
.skill-card:focus-within .skill-card-actions {
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.skill-card-actions button {
  min-height: 30px;
  padding: 5px 10px;
  border: 1px solid #dfe3e8;
  border-radius: 7px;
  background: #dfe3e8;
  color: #151717;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  font: inherit;
  font-size: 0.74rem;
  font-weight: 600;
  cursor: pointer;
  transform: translateY(-3px);
  transition: background 0.15s ease, color 0.15s ease;
}

.skill-card-actions button svg {
  width: 17px;
  height: 17px;
  flex: 0 0 17px;
  fill: currentColor;
  stroke: currentColor;
  stroke-width: 12px;
  stroke-linejoin: round;
  transform: translateY(1px);
}

.skill-card-actions button:hover:not(:disabled) {
  border-color: #d1d6dd;
  background: #d1d6dd;
}

.skill-card-actions button.danger {
  border-color: transparent;
  background: transparent;
  color: #dc2626;
}

.skill-card-actions button.danger:hover:not(:disabled) {
  border-color: transparent;
  background: transparent;
  color: #b91c1c;
}

.skill-card-actions button:disabled {
  opacity: 0.55;
  cursor: not-allowed;
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

@media (max-width: 900px) {
  .project-layout {
    grid-template-columns: minmax(0, 1fr);
  }

  .project-sidebar {
    grid-column: 1;
    grid-row: 1;
    position: static;
    min-height: 0;
    margin-top: 0;
    margin-bottom: 28px;
  }

  .project-workspace {
    grid-column: 1;
    grid-row: 2;
  }

  .toolbar {
    width: 100%;
    margin-left: 0;
  }

  .project-nav {
    position: relative;
    top: auto;
    display: grid;
    grid-template-columns: repeat(4, 1fr);
  }

  .project-nav button {
    padding: 12px 8px;
    border-bottom: 0;
    text-align: center;
  }

  .project-nav-slider {
    display: none;
  }

  .project-nav button.active {
    background: #151717;
    box-shadow: none;
  }

  .project-metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    row-gap: 12px;
  }

  .project-metric:nth-child(3)::after,
  .project-metric:last-child::after {
    display: none;
  }

}

@media (max-width: 560px) {
  .content {
    padding-right: 14px;
    padding-left: 14px;
  }

  .toolbar-right.action-menu.manager-actions {
    width: 282px;
  }

  .toolbar-right.action-menu.manager-actions:hover,
  .toolbar-right.action-menu.manager-actions:focus-within {
    width: 282px;
  }

  .permission-state-card,
  .permission-category-card {
    padding-right: 16px;
    padding-left: 16px;
  }

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
