<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useTeamStore } from '@/stores/teamStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useProjectSyncStore } from '@/stores/projectSyncStore'
import { useTeamSync } from '@/composables/useTeamSync'
import { listNativeSkills, type NativeSkillItem } from '@/api/skillStore'
import {
  listTeamSkillHistory,
  type TeamSkillHistoryItem,
  type TeamMemberInfo,
} from '@/api/teams'
import type { ProjectInfo } from '@/api/projects'
import { useSkillStore } from '@/stores/skillStore'
import { toast } from '@/composables/useToast'
import { getSkeletonCount, setSkeletonCount } from '@/utils/skeletonCount'
import { formatRelativeTime } from '@/utils/relativeTime'
import { versionNumberOf } from '@/utils/versionNumber'
import { useDirectionalTransition } from '@/composables/useDirectionalTransition'
import AppTopNav from '@/components/AppTopNav.vue'
import AddSkillModal from '@/components/AddSkillModal.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import SyncStatusBadge from '@/components/SyncStatusBadge.vue'
import cursorIcon from '@/img/icon/cursor.svg'
import codexIcon from '@/img/icon/codex.svg'
import windsurfIcon from '@/img/icon/windsurf.svg'
import claudeIcon from '@/img/icon/claudecode.svg'
import kiroIcon from '@/img/icon/kiro.svg'
import traeIcon from '@/img/icon/trae.svg'
import qoderIcon from '@/img/icon/qoder.svg'
import workbuddyIcon from '@/img/icon/workbuddy.svg'
import teamEmptyImg from '@/img/status/team_empty.png'

// 团队工作台：与全局 AppTopNav 共用外壳。
// 当前激活的团队来自 workspaceStore.activeTeamId；标签页（团队 SKILL / 团队项目）
// 由路由 name 驱动，对应顶栏中间的导航项。

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const teamStore = useTeamStore()
const workspace = useWorkspaceStore()
const projectStore = useProjectSyncStore()
const skillStore = useSkillStore()

// 与个人仓库（Dashboard）完全一致的卡片信息：平台部署图标、描述、相对时间。
const platforms = [
  { key: 'cursor', label: 'Cursor', icon: cursorIcon },
  { key: 'codex', label: 'Codex', icon: codexIcon },
  { key: 'windsurf', label: 'Windsurf', icon: windsurfIcon },
  { key: 'claude', label: 'Claude Code', icon: claudeIcon },
  { key: 'kiro', label: 'Kiro', icon: kiroIcon },
  { key: 'trae', label: 'Trae', icon: traeIcon },
  { key: 'qoder', label: 'Qoder', icon: qoderIcon },
  { key: 'workbuddy', label: 'WorkBuddy', icon: workbuddyIcon },
] as const

function deployedOn(skill: NativeSkillItem): Record<string, boolean> {
  return skillStore.installedStatus(skill) as unknown as Record<string, boolean>
}

function skillDesc(s: NativeSkillItem): string {
  return s.short_description || s.description || '暂无描述'
}

// 「最近一次提交」时间：后端返回的是无时区服务器时间字符串，
// 直接按字符切片格式化为「YYYY-MM-DD HH:mm」，避免本地时区漂移。
function formatCommitTime(iso: string | null): string {
  if (!iso) return ''
  const date = iso.slice(0, 10)
  const time = iso.slice(11, 16)
  return time ? `${date} ${time}` : date
}

// 顶栏中间导航对应的标签：team-projects → 项目；team-manage → 团队管理；其余 → 团队 SKILL。
const activeTab = computed<'skill' | 'projects' | 'manage'>(() => {
  if (route.name === 'team-projects') return 'projects'
  if (route.name === 'team-manage') return 'manage'
  return 'skill'
})

// 顶栏标签切换时，正文内容按导航方向横向滑入滑出（右滑入 / 左滑出，反向则相反）。
const {
  name: panelTransition,
  animating: panelAnimating,
  end: panelTransitionEnd,
} = useDirectionalTransition({
  value: () => activeTab.value,
  order: ['skill', 'projects', 'manage'],
  names: { forward: 'panel-forward', backward: 'panel-backward' },
})

const showCreateProject = ref(false)
const newProjectName = ref('')
const newProjectDesc = ref('')
// 项目卡片上的编辑入口
const showEditProject = ref(false)
const editProjectTarget = ref<ProjectInfo | null>(null)
const editProjectName = ref('')
const editProjectDescription = ref('')
const projectSaving = ref(false)
// 删除项目确认弹窗（应用内弹窗，替代浏览器 window.confirm）
const showDeleteProject = ref(false)
const deleteTarget = ref<{ id: string; name: string } | null>(null)
const deletingProject = ref(false)
// 解散团队确认弹窗（应用内弹窗，替代浏览器 window.confirm）
const showDissolveTeam = ref(false)
const dissolvingTeam = ref(false)
const settingsSaving = ref(false)
const teamSkills = ref<NativeSkillItem[]>([])
// 区分“真的没有 Skill”与“加载失败（慢/弱网/全局 VPN 抖动超时）”：
// 失败时不要把列表清空成“暂无”，而是提示可重试，避免掩盖真实错误。
const teamSkillsError = ref(false)
// 团队 Skill / 项目加载态 + 骨架屏数量（取上次后端返回的真实个数）。
const teamSkillsLoading = ref(false)
const DEFAULT_SKILL_SKELETON = 6
const DEFAULT_PROJECT_SKELETON = 3
const teamSkillSkeletonCount = ref(DEFAULT_SKILL_SKELETON)
const projectSkeletonCount = ref(DEFAULT_PROJECT_SKELETON)

// —— 新增 Skill 到团队仓库（弹窗内的方式/解析/导入逻辑见 AddSkillModal 组件）——
const showAddSkill = ref(false)

const myRole = computed(() => {
  const uid = authStore.user?.id
  if (!uid || !teamStore.currentTeam) return ''
  if (teamStore.currentTeam.owner_id === uid) return 'owner'
  return teamStore.members.find((m) => m.user_id === uid)?.role || ''
})

const canManageProjects = computed(() =>
  ['owner', 'admin'].includes(myRole.value),
)

const isOwner = computed(() => myRole.value === 'owner')

// —— 角色 / 来源文案本地化 ——
const ROLE_LABELS: Record<string, string> = {
  owner: '所有者',
  admin: '管理员',
  member: '成员',
}
function roleLabel(role: string): string {
  return ROLE_LABELS[role] || role
}
const SOURCE_LABELS: Record<string, string> = {
  push: '部署推送',
  web_edit: '网页编辑',
  restore: '版本回滚',
}
function sourceLabel(src: string): string {
  return SOURCE_LABELS[src] || src || '—'
}

// —— 分配权限（仅 owner）——
const showAssignRole = ref(false)
const roleSaving = ref<string | null>(null) // 正在保存的成员 user_id
const ROLE_OPTIONS = [
  { label: '管理员', value: 'admin' },
  { label: '成员', value: 'member' },
]

async function changeRole(member: TeamMemberInfo, role: string) {
  if (member.role === role || roleSaving.value) return
  roleSaving.value = member.user_id
  const res = await teamStore.changeMemberRole(member.user_id, role)
  roleSaving.value = null
  if (res.success) {
    toast.success(
      `已将 ${member.display_name || member.username} 设为${roleLabel(role)}`,
    )
  } else {
    toast.error(res.error || '修改成员角色失败')
  }
}

// —— 提交历史 / 审计（owner + admin）——
const HISTORY_PAGE = 20
const historyItems = ref<TeamSkillHistoryItem[]>([])
const historyLoading = ref(false)
const historyHasMore = ref(false)
const historyFilterSkillId = ref('')

const historySkillOptions = computed(() =>
  teamSkills.value.map((s) => ({ id: s.id, name: s.display_name || s.name || s.id })),
)

// 历史筛选下拉选项（全局 BaseSelect 格式）：首项「全部 Skill」+ 各团队 Skill
const historyFilterOptions = computed(() => [
  { label: '全部 Skill', value: '' },
  ...historySkillOptions.value.map((o) => ({ label: o.name, value: o.id })),
])

async function loadHistory(reset = true) {
  const teamId = teamStore.currentTeamId
  if (!teamId || historyLoading.value) return
  if (reset) historyItems.value = []
  historyLoading.value = true
  try {
    const offset = reset ? 0 : historyItems.value.length
    const res = await listTeamSkillHistory(teamId, {
      skillId: historyFilterSkillId.value || undefined,
      limit: HISTORY_PAGE,
      offset,
    })
    // 乱序保护：返回时若已切到别的团队则丢弃
    if (teamStore.currentTeamId !== teamId) return
    if (res.success) {
      historyItems.value = reset ? res.items : [...historyItems.value, ...res.items]
      historyHasMore.value = res.items.length === HISTORY_PAGE
    }
  } catch {
    // 历史为辅助视图，失败不阻断管理页
  } finally {
    if (teamStore.currentTeamId === teamId) historyLoading.value = false
  }
}

// 进入团队管理标签且具备管理权限时拉取聚合提交历史；切换团队/获得权限后自动重载。
watch(
  () => [activeTab.value, canManageProjects.value, teamStore.currentTeamId] as const,
  ([tab, canManage]) => {
    if (tab === 'manage' && canManage) loadHistory(true)
  },
  { immediate: true },
)

// —— 团队级实时同步：其他成员的结构性变更自动刷新，无需手动刷新 ——
const { connected: teamSyncConnected } = useTeamSync(
  () => teamStore.currentTeamId,
  async (evt) => {
    const teamId = teamStore.currentTeamId
    if (!teamId || evt.team_id !== teamId) return
    // 自己触发的变更：对应操作已在本地刷新过，跳过以免重复请求与界面闪烁
    if (evt.user_id && evt.user_id === authStore.user?.id) return

    if (evt.type === 'team.deleted') {
      // owner 解散了团队：返回管理团队列表
      teamSkills.value = []
      await teamStore.handleTeamDeleted(teamId)
      backToManage()
    } else if (evt.type.startsWith('project.')) {
      await loadProjects(teamId)
    } else if (evt.type.startsWith('team_skill.')) {
      await loadTeamSkills(teamId)
    } else if (evt.type === 'team.member.joined') {
      await teamStore.selectTeam(teamId)
    }
  },
)

// 避免挂载时与 activeTeamId watch 重复加载同一团队。
let loadingTeamId: string | null = null

async function loadTeam(teamId: string) {
  if (loadingTeamId === teamId) return
  loadingTeamId = teamId
  // 进入团队前先按上次缓存的真实个数渲染骨架屏（项目 / 团队 Skill 各自独立）。
  teamSkillSkeletonCount.value = getSkeletonCount(`skills:team:${teamId}`, DEFAULT_SKILL_SKELETON)
  projectSkeletonCount.value = getSkeletonCount(`projects:${teamId}`, DEFAULT_PROJECT_SKELETON)
  // 切换瞬间清空上一个团队的项目/Skill，避免网络返回前右侧串味
  projectStore.projects = []
  teamSkills.value = []
  teamSkillsError.value = false
  try {
    // 团队详情/成员、项目列表、团队 Skill 三类数据相互独立 —— 并行拉取。
    await Promise.all([
      teamStore.selectTeam(teamId),
      loadProjects(teamId),
      loadTeamSkills(teamId),
    ])
  } finally {
    if (loadingTeamId === teamId) loadingTeamId = null
  }
}

// 拉取项目列表并把后端返回的真实个数缓存，供下次骨架屏使用。
async function loadProjects(teamId: string) {
  await projectStore.fetchProjects(teamId)
  if (teamStore.currentTeamId === teamId || projectStore.projects.length) {
    setSkeletonCount(`projects:${teamId}`, projectStore.projects.length)
  }
}

async function loadTeamSkills(teamId: string) {
  teamSkillsLoading.value = true
  try {
    const res = await listNativeSkills('team')
    // 乱序保护：返回时若已切到别的团队，丢弃本次结果
    if (teamStore.currentTeamId !== teamId) return
    if (res.success) {
      teamSkills.value = res.skills.filter((s) => s.team_id === teamId)
      teamSkillsError.value = false
      // 回写本团队真实 Skill 个数，下次进入按此渲染等量骨架屏。
      setSkeletonCount(`skills:team:${teamId}`, teamSkills.value.length)
    } else {
      // 后端返回失败：标记错误，但不要把已有/乐观插入的卡片清空成“暂无”
      teamSkillsError.value = true
    }
  } catch {
    // 网络失败（后端慢、弱网，或全局 VPN 把国内云流量绕境外导致超时/抖动）：
    // 保留现有列表并标记加载失败，避免把“加载失败”误显示为“该团队暂无 Skill”。
    if (teamStore.currentTeamId === teamId) teamSkillsError.value = true
  } finally {
    if (teamStore.currentTeamId === teamId) teamSkillsLoading.value = false
  }
}

/** 乐观插入/更新一条团队 Skill 卡片：导入成功后即便随后的刷新失败也能立即显示。 */
function upsertTeamSkill(skill: NativeSkillItem) {
  if (skill.team_id !== teamStore.currentTeamId) return
  const i = teamSkills.value.findIndex((s) => s.id === skill.id)
  if (i >= 0) teamSkills.value[i] = skill
  else teamSkills.value.unshift(skill)
}

function flashSkillRepoMsg(msg: string) {
  toast.success(msg)
}

// AddSkillModal 完成回调：
//   - message 非空（完整成功，模态已自行关闭）：乐观插卡 + 刷新列表 + 弹提示。
//   - message 为空（部分失败，模态仍打开内联报错）：仅插入已成功的卡片。
function onAddSkillDone(payload: { message: string; skills?: NativeSkillItem[] }) {
  payload.skills?.forEach(upsertTeamSkill)
  if (payload.message) {
    if (teamStore.currentTeamId) void loadTeamSkills(teamStore.currentTeamId)
    flashSkillRepoMsg(payload.message)
  }
}

async function createProject() {
  if (!newProjectName.value.trim() || !teamStore.currentTeamId) return
  const res = await projectStore.create(
    teamStore.currentTeamId,
    newProjectName.value.trim(),
    newProjectDesc.value.trim(),
  )
  if (res.success) {
    showCreateProject.value = false
    newProjectName.value = ''
    newProjectDesc.value = ''
    toast.success('项目已创建')
  } else {
    toast.error(res.error || '创建失败')
  }
}

function openEditProject(project: ProjectInfo) {
  editProjectTarget.value = project
  editProjectName.value = project.name
  editProjectDescription.value = project.description || ''
  showEditProject.value = true
}

async function saveProject() {
  const project = editProjectTarget.value
  const name = editProjectName.value.trim()
  if (!project || projectSaving.value) return
  if (!name) {
    toast.warning('项目名称不能为空')
    return
  }

  const description = editProjectDescription.value.trim()
  if (name === project.name && description === (project.description || '')) {
    showEditProject.value = false
    return
  }

  projectSaving.value = true
  const res = await projectStore.update(project.id, name, description)
  projectSaving.value = false
  if (res.success) {
    showEditProject.value = false
    editProjectTarget.value = null
    toast.success('项目信息已保存')
  } else {
    toast.error(res.error || '保存项目信息失败')
  }
}

async function toggleAutoHotUpdate(event: Event) {
  if (!teamStore.currentTeam) return
  const checked = (event.target as HTMLInputElement).checked
  const previous = teamStore.currentTeam.auto_skill_hot_update
  settingsSaving.value = true
  teamStore.currentTeam.auto_skill_hot_update = checked
  const res = await teamStore.updateSettings(checked)
  if (!res.success) {
    teamStore.currentTeam.auto_skill_hot_update = previous
    toast.error(res.error || '保存团队设置失败')
  }
  settingsSaving.value = false
}

// —— 团队名称 / 描述行内编辑（owner/admin） ——
const editingProfile = ref(false)
const profileSaving = ref(false)
const editName = ref('')
const editDesc = ref('')

function startEditProfile() {
  if (!teamStore.currentTeam) return
  editName.value = teamStore.currentTeam.name
  editDesc.value = teamStore.currentTeam.description || ''
  editingProfile.value = true
}

function cancelEditProfile() {
  editingProfile.value = false
}

async function saveProfile() {
  if (!teamStore.currentTeam) return
  const name = editName.value.trim()
  if (!name) {
    toast.warning('团队名称不能为空')
    return
  }
  profileSaving.value = true
  const res = await teamStore.updateProfile(name, editDesc.value.trim())
  profileSaving.value = false
  if (res.success) {
    editingProfile.value = false
    toast.success('团队信息已保存')
  } else {
    toast.error(res.error || '保存团队信息失败')
  }
}

function goToProject(projectId: string) {
  router.push(`/projects/${projectId}`)
}

function askRemoveProject(projectId: string, name: string) {
  deleteTarget.value = { id: projectId, name }
  showDeleteProject.value = true
}

async function confirmRemoveProject() {
  const target = deleteTarget.value
  if (!target || deletingProject.value) return
  deletingProject.value = true
  const res = await projectStore.remove(target.id)
  deletingProject.value = false
  if (res.success) {
    showDeleteProject.value = false
    deleteTarget.value = null
    toast.success('项目已删除')
  } else {
    toast.error(res.error || '删除项目失败')
  }
}

function askRemoveTeam() {
  if (!teamStore.currentTeam) return
  showDissolveTeam.value = true
}

async function confirmRemoveTeam() {
  const team = teamStore.currentTeam
  if (!team || dissolvingTeam.value) return
  dissolvingTeam.value = true
  const res = await teamStore.remove(team.id)
  dissolvingTeam.value = false
  if (res.success) {
    showDissolveTeam.value = false
    toast.success('团队已解散')
    backToManage()
  } else {
    toast.error(res.error || '删除团队失败')
  }
}

// 团队被解散 / 当前无团队：清空并回到个人空间（团队的创建/加入入口已移至头像菜单）。
function backToManage() {
  teamStore.clearCurrent()
  workspace.switchToPersonal()
  router.push('/')
}

onMounted(async () => {
  workspace.init()
  if (!teamStore.teams.length) await teamStore.fetchTeams()
  // 解析当前应进入的团队：优先用持久化的 activeTeamId，失效则退回首个团队。
  let teamId = workspace.activeTeamId
  if (!teamId || !teamStore.teams.some((t) => t.id === teamId)) {
    teamId = teamStore.teams[0]?.id ?? null
  }
  if (!teamId) {
    // 没有任何团队 → 回到个人空间（可在头像菜单里创建/加入团队）
    workspace.switchToPersonal()
    router.replace('/')
    return
  }
  // 同步空间状态（让右侧切换器与中间导航反映该团队）
  workspace.switchToTeam(teamId)
  await loadTeam(teamId)
})

// 在工作台内通过右侧切换器换团队时重新加载数据
watch(
  () => workspace.activeTeamId,
  (teamId) => {
    if (teamId) loadTeam(teamId)
  },
)
</script>

<template>
  <div class="team-workspace">
    <AppTopNav />

    <main class="team-main">
      <template v-if="teamStore.currentTeam">
        <div class="panel-wrap" :class="{ animating: panelAnimating }">
        <transition
          :name="panelTransition"
          @after-enter="panelTransitionEnd"
          @after-leave="panelTransitionEnd"
          @enter-cancelled="panelTransitionEnd"
        >
        <!-- 团队 SKILL（顶部 UI 参考个人 SKILL 仓库：标题 + 同步徽章 + 右侧新增） -->
        <section v-if="activeTab === 'skill'" key="skill" class="tab-panel">
          <div class="repo-toolbar">
            <div class="repo-titles">
              <h1 class="repo-title">{{ teamStore.currentTeam.name }}</h1>
              <SyncStatusBadge :connected="teamSyncConnected" />
            </div>
            <button class="btn-add" @click="showAddSkill = true">
              <span class="plus">+</span> 新增 Skill
            </button>
          </div>
          <!-- 加载骨架（数量取上次后端返回的真实个数） -->
          <div v-if="teamSkillsLoading && !teamSkills.length" class="skill-grid">
            <div v-for="i in teamSkillSkeletonCount" :key="i" class="skill-card skeleton">
              <div class="sk-line sk-title"></div>
              <div class="sk-line sk-text"></div>
              <div class="sk-line sk-text short"></div>
              <div class="sk-line sk-foot"></div>
            </div>
          </div>
          <div v-else-if="teamSkills.length" class="skill-grid">
            <div
              v-for="s in teamSkills"
              :key="s.id"
              class="skill-card"
              @click="router.push('/skills/' + s.id)"
            >
              <div class="card-head">
                <span class="card-name">{{ s.display_name || s.name || s.id }}</span>
                <span class="card-version">v{{ s.version }}</span>
              </div>
              <p class="card-desc">{{ skillDesc(s) }}</p>
              <div v-if="s.tags?.length" class="card-tags">
                <span v-for="tag in s.tags.slice(0, 4)" :key="tag" class="tag">{{ tag }}</span>
                <span v-if="s.tags.length > 4" class="tag more">+{{ s.tags.length - 4 }}</span>
              </div>
              <div class="card-foot">
                <div class="platform-icons">
                  <img
                    v-for="p in platforms"
                    :key="p.key"
                    :src="p.icon"
                    :alt="p.label"
                    :title="`${p.label}${deployedOn(s)[p.key] ? '：已部署' : '：未部署'}`"
                    :class="['platform-icon', { deployed: deployedOn(s)[p.key] }]"
                  />
                </div>
                <span v-if="s.updated_at" class="card-time">{{ formatRelativeTime(s.updated_at) }}</span>
              </div>
            </div>
          </div>
          <div v-else-if="teamSkillsError" class="empty-hint load-error">
            团队 Skill 加载失败（网络较慢或不稳定，如开启了全局 VPN 请尝试关闭或为本服务设置直连）。
            <button
              class="link-btn"
              @click="teamStore.currentTeamId && loadTeamSkills(teamStore.currentTeamId)"
            >
              点击重试
            </button>
          </div>
          <div v-else class="team-empty">
            <img :src="teamEmptyImg" alt="" draggable="false" />
            <h3>该团队还没有 Skill</h3>
            <p>新建或导入一个 Skill，团队成员即可共享使用</p>
          </div>
        </section>

        <!-- 团队项目（顶部 UI 参考团队 SKILL：标题 + 同步徽章 + 右侧新建项目） -->
        <section v-else-if="activeTab === 'projects'" key="projects" class="tab-panel">
          <div class="repo-toolbar">
            <div class="repo-titles">
              <h1 class="repo-title">{{ teamStore.currentTeam.name }}</h1>
              <SyncStatusBadge :connected="teamSyncConnected" />
            </div>
            <button class="btn-add" @click="showCreateProject = true">
              <span class="plus">+</span> 新建项目
            </button>
          </div>

          <!-- 加载骨架（数量取上次后端返回的真实个数） -->
          <div v-if="projectStore.loading && !projectStore.projects.length" class="project-grid">
            <div v-for="i in projectSkeletonCount" :key="i" class="project-card skeleton">
              <div class="sk-line sk-title"></div>
              <div class="sk-line sk-text"></div>
              <div class="sk-line sk-meta"></div>
            </div>
          </div>
          <div v-else-if="projectStore.projects.length" class="project-grid">
            <div
              v-for="project in projectStore.projects"
              :key="project.id"
              class="project-card"
              @click="goToProject(project.id)"
            >
              <button
                v-if="canManageProjects"
                class="project-delete"
                title="删除项目"
                @click.stop="askRemoveProject(project.id, project.name)"
              >
                ×
              </button>
              <div class="project-head" :class="{ 'has-delete': canManageProjects }">
                <div class="project-title-group">
                  <h4 class="project-title">{{ project.name }}</h4>
                  <button
                    v-if="canManageProjects"
                    class="project-edit"
                    title="编辑项目名称与描述"
                    aria-label="编辑项目名称与描述"
                    @click.stop="openEditProject(project)"
                  >
                    <svg viewBox="0 0 1024 1024" width="16" height="16" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M469.333333 128a42.666667 42.666667 0 0 1 0 85.333333H213.333333v597.333334h597.333334v-256l0.298666-4.992A42.666667 42.666667 0 0 1 896 554.666667v256a85.333333 85.333333 0 0 1-85.333333 85.333333H213.333333a85.333333 85.333333 0 0 1-85.333333-85.333333V213.333333a85.333333 85.333333 0 0 1 85.333333-85.333333z m414.72 12.501333a42.666667 42.666667 0 0 1 0 60.330667L491.861333 593.066667a42.666667 42.666667 0 0 1-60.330666-60.330667l392.192-392.192a42.666667 42.666667 0 0 1 60.330666 0z" fill="currentColor"></path>
                    </svg>
                  </button>
                </div>
                <span class="project-date">{{ project.created_at?.slice(0, 10) }}</span>
              </div>
              <p class="project-desc">{{ project.description || '暂无描述' }}</p>

              <div class="project-tags">
                <span v-if="project.pending_commit_count" class="stat-tag tag-commit">
                  <svg class="stat-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <circle cx="12" cy="12" r="9"></circle>
                    <path d="M12 7.5V12l3 1.8"></path>
                  </svg>
                  {{ project.pending_commit_count }} 项待提交
                </span>
                <span v-if="project.pending_update_count" class="stat-tag tag-update">
                  <svg class="stat-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <circle cx="12" cy="12" r="9"></circle>
                    <path d="M8.5 13L12 9.5l3.5 3.5"></path>
                  </svg>
                  {{ project.pending_update_count }} 项待更新
                </span>
                <span class="stat-tag tag-link">
                  <svg class="stat-icon" viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M10 13a4 4 0 0 0 6 .4l2.5-2.5a4 4 0 0 0-5.7-5.7l-1.4 1.4"></path>
                    <path d="M14 11a4 4 0 0 0-6-.4l-2.5 2.5a4 4 0 0 0 5.7 5.7l1.4-1.4"></path>
                  </svg>
                  关联 {{ project.skill_count }} 个 Skill
                </span>
              </div>

              <div class="project-foot">
                <div class="project-commit">
                  <svg class="stat-icon" viewBox="0 0 1024 1024" width="14" height="14" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M557.481057 77.283019a431.335849 431.335849 0 1 1-294.873359 746.128906 34.062491 34.062491 0 1 1 46.58234-49.692982 363.230189 363.230189 0 1 0-114.93917-268.288l43.703547-43.587622a34.04317 34.04317 0 0 1 45.712906-2.221887l2.434415 2.202566a34.04317 34.04317 0 0 1 2.202566 45.751547l-2.202566 2.434415-80.277736 80.258415a56.745057 56.745057 0 0 1-77.611472 2.55034l-2.724226-2.56966-80.277736-80.258415a34.04317 34.04317 0 0 1 45.751547-50.369208l2.434415 2.202566 32.845283 32.845283A431.316528 431.316528 0 0 1 557.481057 77.283019z m-11.341283 181.615094a34.04317 34.04317 0 0 1 34.043169 34.04317v190.058264l134.742944 134.704302a34.04317 34.04317 0 0 1 2.337811 45.635623l-2.337811 2.588981a34.062491 34.062491 0 0 1-48.166642 0l-142.973585-142.973585a33.985208 33.985208 0 0 1-11.766339-25.735245V292.941283a34.04317 34.04317 0 0 1 34.04317-34.04317z" fill="currentColor"></path>
                  </svg>
                  <span v-if="project.last_commit_at">最近提交：{{ formatCommitTime(project.last_commit_at) }}</span>
                  <span v-else class="muted">暂无提交记录</span>
                </div>
              </div>
            </div>
          </div>

          <div v-else class="team-empty">
            <img :src="teamEmptyImg" alt="" draggable="false" />
            <h3>该团队还没有项目</h3>
            <p>新建一个项目，把团队 Skill 组织起来协作</p>
          </div>
        </section>

        <!-- 团队管理（顶部与团队项目一致；信息 / 成员独立白底卡片） -->
        <section v-else key="manage" class="tab-panel">
          <div class="repo-toolbar">
            <div class="repo-titles">
              <h1 v-if="!editingProfile" class="repo-title">{{ teamStore.currentTeam.name }}</h1>
              <input
                v-else
                v-model="editName"
                class="repo-title repo-title-edit"
                maxlength="40"
                placeholder="团队名称"
                @keyup.enter="saveProfile"
              />
              <template v-if="!editingProfile">
                <button
                  v-if="canManageProjects"
                  class="btn-icon-edit"
                  title="编辑团队名称与描述"
                  @click="startEditProfile"
                >
                  <svg viewBox="0 0 1024 1024" width="18" height="18" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M469.333333 128a42.666667 42.666667 0 0 1 0 85.333333H213.333333v597.333334h597.333334v-256l0.298666-4.992A42.666667 42.666667 0 0 1 896 554.666667v256a85.333333 85.333333 0 0 1-85.333333 85.333333H213.333333a85.333333 85.333333 0 0 1-85.333333-85.333333V213.333333a85.333333 85.333333 0 0 1 85.333333-85.333333z m414.72 12.501333a42.666667 42.666667 0 0 1 0 60.330667L491.861333 593.066667a42.666667 42.666667 0 0 1-60.330666-60.330667l392.192-392.192a42.666667 42.666667 0 0 1 60.330666 0z" fill="currentColor"></path>
                  </svg>
                </button>
              </template>
              <template v-else>
                <button class="btn-text save" :disabled="profileSaving" @click="saveProfile">
                  {{ profileSaving ? '保存中…' : '保存' }}
                </button>
                <button class="btn-text" :disabled="profileSaving" @click="cancelEditProfile">取消</button>
              </template>
            </div>
            <div v-if="isOwner" class="toolbar-actions">
              <button
                class="btn-add btn-add-assign"
                title="给成员分配管理员 / 成员权限"
                @click="showAssignRole = true"
              >
                分配权限
              </button>
              <button
                class="btn-add btn-add-danger"
                title="解散团队（不可恢复）"
                @click="askRemoveTeam"
              >
                解散团队
              </button>
            </div>
          </div>

          <!-- 团队信息（标题在卡片外） -->
          <div class="manage-section-title">团队信息</div>
          <div class="manage-card">
            <div class="info-row">
              <span class="info-label">团队描述</span>
              <span v-if="!editingProfile" class="info-value">{{ teamStore.currentTeam.description || '暂无描述' }}</span>
              <input
                v-else
                v-model="editDesc"
                class="info-value info-value-edit"
                maxlength="200"
                placeholder="一句话介绍团队职责"
                @keyup.enter="saveProfile"
              />
            </div>
            <div class="info-row">
              <span class="info-label">邀请码</span>
              <code class="invite-code-chip">{{ teamStore.currentTeam.invite_code }}</code>
            </div>
            <div class="info-row">
              <span class="info-label">Skill 自动热更新</span>
              <label class="setting-toggle">
                <input
                  type="checkbox"
                  :checked="teamStore.currentTeam.auto_skill_hot_update"
                  :disabled="settingsSaving"
                  @change="toggleAutoHotUpdate"
                />
                <span>{{ teamStore.currentTeam.auto_skill_hot_update ? '已开启' : '已关闭' }}</span>
              </label>
            </div>
          </div>

          <!-- 团队成员（标题在卡片外，单独白底卡片） -->
          <div class="manage-section-title">
            团队成员
            <span class="member-count">{{ teamStore.members.length }}</span>
          </div>
          <div class="manage-card">
            <ul class="member-list">
              <li v-for="m in teamStore.members" :key="m.user_id">
                <span class="member-avatar">{{ (m.display_name || m.username || '?').slice(0, 1).toUpperCase() }}</span>
                <span class="member-name">{{ m.display_name || m.username }}</span>
                <span class="member-role" :class="`role-${m.role}`">{{ roleLabel(m.role) }}</span>
              </li>
              <li v-if="!teamStore.members.length" class="member-empty">暂无成员</li>
            </ul>
          </div>

          <!-- 提交历史 / 审计（仅 owner / admin 可见） -->
          <template v-if="canManageProjects">
            <div class="manage-section-title">
              提交历史 / 审计
              <BaseSelect
                v-if="historySkillOptions.length"
                v-model="historyFilterSkillId"
                class="history-filter"
                :options="historyFilterOptions"
                :block="false"
                pill
                @change="loadHistory(true)"
              />
            </div>
            <div class="manage-card">
              <ul v-if="historyItems.length" class="history-list">
                <li v-for="h in historyItems" :key="h.id" class="history-item">
                  <div class="history-head">
                    <span class="history-skill">{{ h.skill_name }}</span>
                    <span class="history-seq">v{{ versionNumberOf(h) }}</span>
                    <span class="history-source" :class="`src-${h.source}`">{{ sourceLabel(h.source) }}</span>
                  </div>
                  <div class="history-summary">{{ h.change_summary || '（无变更说明）' }}</div>
                  <div class="history-meta">
                    <span>{{ h.created_by_name || h.created_by || '—' }}</span>
                    <span class="dot">·</span>
                    <span>{{ formatCommitTime(h.created_at) }}</span>
                    <template v-if="h.resource_count">
                      <span class="dot">·</span>
                      <span>{{ h.resource_count }} 个资源</span>
                    </template>
                  </div>
                </li>
              </ul>
              <div v-else-if="historyLoading" class="history-empty">加载中…</div>
              <div v-else class="history-empty">暂无提交记录</div>
              <button
                v-if="historyHasMore"
                class="history-more"
                :disabled="historyLoading"
                @click="loadHistory(false)"
              >
                {{ historyLoading ? '加载中…' : '加载更多' }}
              </button>
            </div>
          </template>
        </section>
        </transition>
        </div>
      </template>

      <!-- 团队数据加载中的占位 -->
      <div v-else class="loading-hint">正在加载团队…</div>
    </main>

    <!-- 创建项目弹窗 -->
    <BaseModal v-model="showCreateProject" title="新建项目">
      <div class="field">
        <label>项目名称</label>
        <input v-model="newProjectName" placeholder="输入项目名称" />
      </div>
      <div class="field">
        <label>描述（可选）</label>
        <input v-model="newProjectDesc" placeholder="项目描述" />
      </div>
      <template #footer>
        <button class="btn-sm btn-primary" @click="createProject">创建</button>
      </template>
    </BaseModal>

    <!-- 编辑项目信息弹窗（入口位于项目卡片） -->
    <BaseModal
      v-model="showEditProject"
      title="编辑项目信息"
      :closable="!projectSaving"
      :close-on-overlay="!projectSaving"
    >
      <div class="field">
        <label>项目名称</label>
        <input
          v-model="editProjectName"
          maxlength="128"
          placeholder="输入项目名称"
          @keyup.enter="saveProject"
        />
      </div>
      <div class="field">
        <label>项目描述</label>
        <textarea
          v-model="editProjectDescription"
          rows="4"
          placeholder="输入项目描述（可选）"
        ></textarea>
      </div>
      <template #footer>
        <button
          class="btn-sm btn-cancel"
          :disabled="projectSaving"
          @click="showEditProject = false"
        >
          取消
        </button>
        <button
          class="btn-sm btn-primary"
          :disabled="projectSaving || !editProjectName.trim()"
          @click="saveProject"
        >
          {{ projectSaving ? '保存中…' : '保存' }}
        </button>
      </template>
    </BaseModal>

    <!-- 删除项目确认弹窗 -->
    <BaseModal
      v-model="showDeleteProject"
      title="删除项目"
      :closable="!deletingProject"
      :close-on-overlay="!deletingProject"
    >
      <p class="confirm-text">
        确认删除项目「<strong>{{ deleteTarget?.name }}</strong>」？
      </p>
      <p class="confirm-hint">
        该项目下的 Skill 关联、部署记录与动态将一并删除，且不可恢复。
      </p>
      <template #footer>
        <button class="btn-sm btn-cancel" :disabled="deletingProject" @click="showDeleteProject = false">
          取消
        </button>
        <button class="btn-sm btn-danger" :disabled="deletingProject" @click="confirmRemoveProject">
          {{ deletingProject ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </BaseModal>

    <!-- 解散团队确认弹窗 -->
    <BaseModal
      v-model="showDissolveTeam"
      title="解散团队"
      :closable="!dissolvingTeam"
      :close-on-overlay="!dissolvingTeam"
    >
      <p class="confirm-text">
        确认解散团队「<strong>{{ teamStore.currentTeam?.name }}</strong>」？
      </p>
      <p class="confirm-hint">
        该团队下的所有项目、团队 Skill 仓库、部署记录、动态与成员关系将一并删除，且不可恢复。各成员本地已部署的文件需自行清理。
      </p>
      <template #footer>
        <button class="btn-sm btn-cancel" :disabled="dissolvingTeam" @click="showDissolveTeam = false">
          取消
        </button>
        <button class="btn-sm btn-danger" :disabled="dissolvingTeam" @click="confirmRemoveTeam">
          {{ dissolvingTeam ? '解散中…' : '确认解散' }}
        </button>
      </template>
    </BaseModal>

    <!-- 分配权限（仅 owner）：给成员设置 管理员 / 成员 角色 -->
    <BaseModal v-model="showAssignRole" title="分配权限" width="460px">
      <p class="assign-hint">仅所有者可调整成员角色。管理员可编辑团队信息、查看提交历史。</p>
      <ul class="assign-list">
        <li v-for="m in teamStore.members" :key="m.user_id" class="assign-row">
          <span class="member-avatar">{{ (m.display_name || m.username || '?').slice(0, 1).toUpperCase() }}</span>
          <span class="assign-name">{{ m.display_name || m.username }}</span>
          <span v-if="m.role === 'owner'" class="member-role role-owner">所有者</span>
          <BaseSelect
            v-else
            class="assign-select"
            :model-value="m.role"
            :options="ROLE_OPTIONS"
            :block="false"
            pill
            :disabled="roleSaving === m.user_id"
            @change="changeRole(m, String($event))"
          />
        </li>
        <li v-if="!teamStore.members.length" class="member-empty">暂无成员</li>
      </ul>
    </BaseModal>

    <!-- 新增 Skill 到团队仓库（方式/解析/导入逻辑见共享组件 AddSkillModal） -->
    <AddSkillModal
      v-model="showAddSkill"
      scope="team"
      :team-id="teamStore.currentTeamId"
      @done="onAddSkillDone"
    />
  </div>
</template>

<style scoped>
.team-workspace {
  min-height: 100vh;
  background: var(--canvas);
  --card-border: #d1d5db;
  --card-border-hover: #151717;
  --card-shadow: 0 1px 3px rgba(47, 51, 66, 0.06);
  --card-shadow-hover: 0 8px 20px rgba(47, 51, 66, 0.1);
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
  /* 标签切换的滑动过场会让面板瞬间横向平移出视口，撑出页面横向滚动条（紫色滑块看着像底部进度条）。
     用 overflow-x: clip 永久裁剪横向溢出，避免依赖动画期标志位（快速切换时有时序竞态会漏出滚动条）。
     clip 不创建滚动容器、保留 overflow-y: visible，不影响顶栏 sticky 与卡片悬停阴影。 */
  overflow-x: clip;
}

.team-main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 24px 32px;
}

.loading-hint {
  text-align: center;
  color: #9ca3af;
  font-size: 0.88rem;
  padding: 4rem 1rem;
}

/* 团队 SKILL 顶部工具栏（参考个人 SKILL 仓库） */
.repo-toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.75rem;
}
.repo-titles {
  display: flex;
  align-items: center;
  gap: 0.7rem;
}
.repo-title {
  margin: 0;
  font-size: 1.6rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #151717;
}

.btn-add {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.55rem 1.1rem;
  border: none;
  border-radius: 9px;
  background: #151717;
  color: #ffffff;
  font-size: 0.88rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  flex-shrink: 0;
  transition: background 0.15s ease, transform 0.1s ease;
}
.btn-add:hover { background: #2d2f2f; }
.btn-add:active { transform: scale(0.98); }
.btn-add .plus { font-size: 1.05rem; line-height: 1; }

/* 团队名称行内编辑：图标按钮（无边框，仅悬停淡底） */
.btn-icon-edit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  padding: 0;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  transform: translateY(2px);
  transition: background 0.15s ease, color 0.15s ease;
}
.btn-icon-edit:hover { background: rgba(21, 23, 23, 0.06); color: #151717; }

/* 编辑态操作：纯文字按钮，不加外框 */
.btn-text {
  padding: 0.2rem 0.4rem;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: #9ca3af;
  font-size: 0.85rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: color 0.15s ease;
}
.btn-text:hover:not(:disabled) { color: #151717; }
.btn-text:disabled { opacity: 0.55; cursor: not-allowed; }
.btn-text.save { color: #151717; }
.btn-text.save:hover:not(:disabled) { color: #000000; }

/* 可编辑内容：维持原样式，仅加下划线提示可编辑 */
.repo-title-edit {
  border: none;
  border-bottom: 3px solid #d1d5db;
  border-radius: 0;
  background: transparent;
  padding: 0 2px 2px;
  outline: none;
  font-family: inherit;
  /* 宽度随文字内容自适应（下划线跟随文字长度），并设最小/最大边界 */
  field-sizing: content;
  min-width: 60px;
  max-width: 100%;
}
.repo-title-edit:focus { border-bottom-color: #151717; }

.info-value-edit {
  flex: 1;
  border: none;
  border-bottom: 2px solid #d1d5db;
  border-radius: 0;
  background: transparent;
  padding: 2px 2px 4px;
  outline: none;
  box-sizing: border-box;
  font-family: inherit;
}
.info-value-edit:focus { border-bottom-color: #151717; }

/* 团队管理 */
.btn-add-danger {
  background: #dc2626;
  color: #ffffff;
  border: 1px solid #dc2626;
}
.btn-add-danger:hover { background: #b91c1c; border-color: #b91c1c; }

/* 工具栏右侧多操作按钮组（分配权限 + 解散团队） */
.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

/* 分配权限：团队紫纯色按钮（遵循 solid-color-buttons 规范，边框与底色同色） */
.btn-add-assign {
  background: #4f46e5;
  color: #ffffff;
  border: 1px solid #4f46e5;
}
.btn-add-assign:hover { background: #4338ca; border-color: #4338ca; }

.manage-error {
  margin-bottom: 16px;
}

/* 团队管理卡片（白底） */
.manage-card {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 16px;
  padding: 20px 24px;
  margin-bottom: 20px;
}
.manage-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 1.05rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #151717;
  margin: 4px 0 12px;
}
.member-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  background: #f1f2f4;
  color: #6b7280;
  font-size: 0.74rem;
  font-weight: 600;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 0;
  border-top: 1px solid #f2f3f5;
}
.info-row:first-of-type {
  border-top: none;
  padding-top: 0;
}
.info-row:last-of-type {
  padding-bottom: 0;
}
.info-label {
  flex-shrink: 0;
  width: 132px;
  font-size: 0.84rem;
  color: #9ca3af;
  font-weight: 500;
}
.info-value {
  flex: 1;
  font-size: 0.88rem;
  color: #374151;
  word-break: break-word;
}
.invite-code-chip {
  background: #eef2ff;
  padding: 3px 10px;
  border-radius: 6px;
  color: #4f46e5;
  font-size: 0.82rem;
  font-family: 'JetBrains Mono', monospace;
}

.setting-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.88rem;
  color: #374151;
  cursor: pointer;
}

.setting-toggle input {
  accent-color: #151717;
}

.section-title {
  font-size: 0.78rem;
  color: #9ca3af;
  font-weight: 600;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.section-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.section-header-row .section-title {
  margin-bottom: 0;
}

/* 标签正文滑动容器：横向滑动跳出正文 1280 限宽，扩展到 90vw 的可视区，
   让面板真正左右平移直至滑出屏幕（而非局限在内容 div 内）。
   用 full-bleed 负边距把容器拉宽到 90vw 居中，不会触发横向滚动条。 */
.panel-wrap {
  display: grid;
  width: 90vw;
  margin-left: calc(50% - 45vw);
}
/* 内部正文仍保持原有 1216px 限宽并居中，布局位置与改动前一致，只有动画行程变宽。 */
.panel-wrap > * {
  grid-area: 1 / 1;
  align-self: start;
  justify-self: center;
  width: 100%;
  max-width: 1216px;
}
/* 仅在切换动画期间裁剪到 90vw，避免位移引发短暂滚动条；静止时不裁剪以保留卡片悬停投影。 */
.panel-wrap.animating {
  overflow: hidden;
}

.panel-forward-enter-active,
.panel-forward-leave-active,
.panel-backward-enter-active,
.panel-backward-leave-active {
  transition: transform 0.5s cubic-bezier(0.32, 0.72, 0, 1), opacity 0.42s ease;
  will-change: transform, opacity;
}
/* 行程 = 半个可视区(45vw) + 自身一半(50%)，保证面板完整滑出 90vw 裁剪区再进入。 */
/* 前进（如 团队SKILL → 团队项目）：新内容自右滑入，旧内容向左滑出 */
.panel-forward-enter-from {
  opacity: 0;
  transform: translateX(calc(45vw + 50%));
}
.panel-forward-leave-to {
  opacity: 0;
  transform: translateX(calc(-45vw - 50%));
}
/* 后退（反向）：新内容自左滑入，旧内容向右滑出 */
.panel-backward-enter-from {
  opacity: 0;
  transform: translateX(calc(-45vw - 50%));
}
.panel-backward-leave-to {
  opacity: 0;
  transform: translateX(calc(45vw + 50%));
}

.success-msg {
  margin-bottom: 12px;
  padding: 0.6rem 1rem;
  border-radius: 10px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
  font-size: 0.84rem;
}

/* 项目卡片网格 / 卡片尺寸与「团队 SKILL」保持一致（同列宽、同间距、同高度基线） */
.project-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.1rem;
  /* 同行卡片等高，配合卡片内 .project-foot 贴底 */
  align-items: stretch;
}

.project-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  min-height: 180px;
  background: #ffffff;
  border: 2px solid var(--card-border);
  border-radius: 16px;
  padding: 1.25rem 1.3rem;
  cursor: pointer;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.project-card:hover {
  border-color: var(--card-border-hover);
  box-shadow: 0 8px 24px rgba(21, 23, 23, 0.07);
  transform: translateY(-2px);
}

.project-delete {
  position: absolute;
  top: 10px;
  right: 10px;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #9ca3af;
  font-size: 18px;
  line-height: 1;
  cursor: pointer;
  opacity: 0;
  transition: opacity 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.project-edit {
  flex-shrink: 0;
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  transform: translateY(1px);
  padding: 0;
  border: 1px solid transparent;
  border-radius: 7px;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.project-card:hover .project-delete {
  opacity: 1;
}

.project-edit:hover {
  background: #f3f4f6;
  color: #151717;
}

.project-delete:hover {
  background: #fef2f2;
  border-color: #fecaca;
  color: #dc2626;
}

.project-error {
  margin-bottom: 12px;
}

/* 标题行：项目名（左）+ 创建日期（右上角，与标题同行） */
.project-head {
  display: flex;
  align-items: center;
  gap: 10px;
}

/* 管理者卡片悬停时右上角会出现删除按钮，预留空间避免与日期重叠 */
.project-head.has-delete {
  padding-right: 22px;
}

.project-title-group {
  display: flex;
  align-items: center;
  gap: 4px;
  flex: 1;
  min-width: 0;
}

.project-title {
  flex: 0 1 auto;
  min-width: 0;
  margin: 0;
  font-size: 0.98rem;
  font-weight: 600;
  color: #151717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-desc {
  margin: 0;
  font-size: 0.84rem;
  line-height: 1.55;
  color: #6b7280;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  /* 预留两行高度，描述长短不改变卡片高度（与团队 SKILL 卡片一致的做法） */
  min-height: 3.1em;
}

/* 最近提交：位于卡片左下角，弱化为辅助信息 */
.project-commit {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 0.76rem;
  color: #9ca3af;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.project-commit .muted {
  color: #b6bcc4;
}

/* 卡片底部：最近提交贴左下角 */
.project-foot {
  margin-top: auto;
  display: flex;
  align-items: center;
}

.project-tags {
  display: flex;
  flex-wrap: nowrap;
  align-items: center;
  gap: 5px;
}

/* 创建日期：移到标题行右上角，被标题（flex:1）推到最右 */
.project-date {
  flex-shrink: 0;
  font-size: 0.74rem;
  color: #b6bcc4;
  white-space: nowrap;
}

/* 三个状态小标签统一使用低对比度灰色 */
.stat-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 999px;
  font-size: 0.72rem;
  font-weight: 400;
  line-height: 1.4;
  white-space: nowrap;
  background: #e5e7eb;
  color: #6b7280;
}

.tag-commit .stat-icon {
  color: #f97316;
}

.tag-update .stat-icon {
  color: #8b5cf6;
}

.tag-link .stat-icon {
  color: #22c55e;
}

/* 三个图标统一为线性图标：同一 viewBox(0 0 24 24) + 同一线宽(stroke-width:2) */
.stat-icon {
  flex-shrink: 0;
  display: block;
  width: 14px;
  height: 14px;
}

/* —— 骨架屏（团队 Skill / 团队项目共用，与个人仓库一致） —— */
.skill-card.skeleton,
.project-card.skeleton {
  cursor: default;
  pointer-events: none;
}

.sk-line {
  border-radius: 6px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}

.skill-card.skeleton {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
}

.sk-title {
  height: 18px;
  width: 55%;
}

.sk-text {
  height: 12px;
  width: 90%;
}

.sk-text.short {
  width: 65%;
}

.sk-foot {
  height: 14px;
  width: 40%;
  margin-top: 0.5rem;
}

.project-card.skeleton .sk-title {
  margin-bottom: 12px;
}

.project-card.skeleton .sk-text {
  margin-bottom: 16px;
}

.sk-meta {
  height: 12px;
  width: 50%;
}

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* —— Skill 卡片：与个人仓库（Dashboard）完全一致 —— */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.1rem;
  /* 同行卡片等高（stretch），配合卡片内 .card-foot 贴底，保证每张卡片尺寸一致 */
  align-items: stretch;
}

.skill-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  /* 固定卡片尺寸：给定高度基线，描述区预留两行，底部信息贴底，
     描述长短（一行/两行）不再改变卡片高度 */
  min-height: 180px;
  padding: 1.25rem 1.3rem;
  border: 2px solid var(--card-border);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: var(--card-shadow);
  cursor: pointer;
}

.skill-card::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: 14px;
  background: radial-gradient(
    ellipse 145% 135% at 0% 100%,
    color-mix(in srgb, var(--card-border-hover) 92%, transparent) 0%,
    color-mix(in srgb, var(--card-border-hover) 50%, transparent) 38%,
    color-mix(in srgb, var(--card-border-hover) 20%, transparent) 70%,
    color-mix(in srgb, var(--card-border-hover) 7%, transparent) 100%
  );
  opacity: 0;
  pointer-events: none;
  z-index: 0;
}

.skill-card > * {
  position: relative;
  z-index: 1;
}

.skill-card:hover {
  border-color: transparent;
  box-shadow: var(--card-shadow-hover);
}

.skill-card:hover::after {
  opacity: 1;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.card-name {
  font-size: 1rem;
  font-weight: 600;
  color: #151717;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.card-version {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: #6b7280;
  background: #f6f7f8;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
}

.card-desc {
  margin: 0;
  font-size: 0.85rem;
  line-height: 1.55;
  color: #6b7280;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  /* 始终预留两行高度（1.55 行高 × 2 行），描述一行时也占满，避免挤压卡片 */
  min-height: 3.1em;
}

.skill-card:hover .card-desc {
  color: #ffffff;
}

.card-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.tag {
  font-size: 0.72rem;
  color: #4b5563;
  background: #e5e7eb;
  border-radius: 999px;
  padding: 0.12rem 0.55rem;
}

.tag.more {
  color: #9ca3af;
}

.card-foot {
  /* 贴到卡片底部：无论描述/标签多少，底部信息行始终对齐在卡片底端 */
  margin-top: auto;
  padding-top: 0.65rem;
  border-top: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.platform-icons {
  display: flex;
  align-items: center;
  gap: 0.7rem;
}

.platform-icon {
  width: 16px;
  height: 16px;
  object-fit: contain;
  opacity: 0.25;
  filter: grayscale(0.15);
  transition: opacity 0.15s ease, filter 0.15s ease;
}

.platform-icon.deployed {
  opacity: 1;
  filter: none;
}

.card-time {
  font-size: 0.74rem;
  color: #b6bcc4;
  white-space: nowrap;
}

.member-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.member-list li {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid #f2f3f5;
  font-size: 0.88rem;
  color: #151717;
}
.member-list li:first-child {
  border-top: none;
  padding-top: 0;
}
.member-list li:last-child {
  padding-bottom: 0;
}

.member-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background: #151717;
  color: #ffffff;
  font-size: 0.8rem;
  font-weight: 600;
  flex-shrink: 0;
}

.member-name {
  flex: 1;
  font-weight: 500;
}

.member-role {
  font-size: 0.72rem;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  border-radius: 999px;
  padding: 0.15rem 0.6rem;
}
/* 角色徽章按角色着色：所有者(琥珀) / 管理员(紫) / 成员(灰) */
.member-role.role-owner { color: #b45309; background: #fef3c7; }
.member-role.role-admin { color: #4f46e5; background: #eef2ff; }
.member-role.role-member { color: #6b7280; background: #f3f4f6; }

.member-empty {
  color: #9ca3af;
  font-size: 0.84rem;
}

/* —— 分配权限弹窗 —— */
.assign-hint {
  margin: 0 0 12px;
  font-size: 0.82rem;
  color: #6b7280;
  line-height: 1.5;
}
.assign-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.assign-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid #f2f3f5;
}
.assign-row:first-child { border-top: none; padding-top: 0; }
.assign-name {
  flex: 1;
  font-size: 0.9rem;
  font-weight: 500;
  color: #151717;
}
.assign-select {
  flex-shrink: 0;
}

/* —— 提交历史 / 审计 —— */
.history-filter {
  margin-left: auto;
}
.history-list {
  list-style: none;
  margin: 0;
  padding: 0;
}
.history-item {
  padding: 12px 0;
  border-top: 1px solid #f2f3f5;
}
.history-item:first-child { border-top: none; padding-top: 0; }
.history-item:last-child { padding-bottom: 0; }
.history-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
}
.history-skill {
  font-size: 0.9rem;
  font-weight: 600;
  color: #151717;
}
.history-seq {
  font-size: 0.72rem;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
}
.history-source {
  font-size: 0.72rem;
  font-weight: 600;
  color: #6b7280;
  background: #f3f4f6;
  border-radius: 999px;
  padding: 0.1rem 0.5rem;
}
.history-source.src-push { color: #ea580c; background: #fff1e6; }
.history-source.src-restore { color: #b45309; background: #fef3c7; }
.history-source.src-web_edit { color: #16a34a; background: #e7f8ee; }
.history-summary {
  font-size: 0.84rem;
  color: #374151;
  line-height: 1.5;
  margin-bottom: 4px;
}
.history-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.75rem;
  color: #9ca3af;
}
.history-meta .dot { color: #d1d5db; }
.history-empty {
  color: #9ca3af;
  font-size: 0.84rem;
  text-align: center;
  padding: 8px 0;
}
.history-more {
  display: block;
  margin: 12px auto 0;
  padding: 0.4rem 1.1rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  font-size: 0.8rem;
  font-weight: 600;
  color: #374151;
  cursor: pointer;
}
.history-more:hover:not(:disabled) { background: #f9fafb; }
.history-more:disabled { opacity: 0.6; cursor: default; }

.empty-hint {
  text-align: center;
  color: #9ca3af;
  font-size: 0.84rem;
  margin-top: 32px;
}

.empty-hint.load-error {
  color: #b45309;
}

/* 空状态插画（团队 Skill / 团队项目为空时展示） */
.team-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 4.5rem 1rem 3rem;
}

.team-empty img {
  width: 380px;
  height: auto;
  /* 插画底部有大片透明留白，用负边距把下方文字拉近 */
  margin-bottom: -5rem;
  user-select: none;
  -webkit-user-drag: none;
}

.team-empty h3 {
  margin: 0 0 0.5rem;
  font-size: 1.1rem;
  font-weight: 600;
  color: #151717;
}

.team-empty p {
  margin: 0;
  font-size: 0.88rem;
  color: #9ca3af;
}

/* 通用组件 */
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

.btn-cancel {
  border: none;
  background: transparent;
}

.btn-cancel:hover {
  background: #f6f7f8;
}

.btn-danger {
  border: none;
  background: #dc2626;
  color: #ffffff;
}

.btn-danger:hover {
  background: #b91c1c;
  color: #ffffff;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-size: 0.82rem;
  color: #6b7280;
  margin-bottom: 6px;
}

.field input,
.field textarea {
  width: 100%;
  padding: 10px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 9px;
  background: #f6f7f8;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.field textarea {
  resize: vertical;
  min-height: 96px;
}

.field input:focus,
.field textarea:focus {
  border-color: #151717;
  background: #ffffff;
}

.error-msg {
  color: #dc2626;
  font-size: 0.82rem;
  margin-bottom: 12px;
}

.confirm-text {
  margin: 0 0 8px;
  font-size: 0.92rem;
  color: #151717;
  line-height: 1.5;
}

.confirm-text strong {
  font-weight: 600;
  word-break: break-all;
}

.confirm-hint {
  margin: 0 0 4px;
  font-size: 0.82rem;
  color: #6b7280;
  line-height: 1.5;
}

.link-btn {
  background: none;
  border: none;
  color: #4f46e5;
  font-size: 0.78rem;
  font-family: inherit;
  cursor: pointer;
  padding: 0;
}

.link-btn:hover {
  text-decoration: underline;
}
</style>
