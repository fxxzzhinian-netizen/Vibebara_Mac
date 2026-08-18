<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useTeamStore } from '@/stores/teamStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useProjectSyncStore } from '@/stores/projectSyncStore'
import { useTeamSync } from '@/composables/useTeamSync'
import { listNativeSkills, type NativeSkillItem } from '@/api/skillStore'
import type { TeamMemberInfo } from '@/api/teams'
import { useSkillStore } from '@/stores/skillStore'
import { toast } from '@/composables/useToast'
import { getSkeletonCount, setSkeletonCount } from '@/utils/skeletonCount'
import { formatRelativeTime } from '@/utils/relativeTime'
import { useDirectionalTransition } from '@/composables/useDirectionalTransition'
import AppTopNav from '@/components/AppTopNav.vue'
import AppEmptyState from '@/components/AppEmptyState.vue'
import AddSkillModal from '@/components/AddSkillModal.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import SyncStatusBadge from '@/components/SyncStatusBadge.vue'
import UserAvatar from '@/components/UserAvatar.vue'
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

const memberGroups = computed(() => [
  {
    role: 'owner',
    label: '所有者',
    description: '拥有团队全部管理权限',
    members: teamStore.members.filter((member) => member.role === 'owner'),
  },
  {
    role: 'admin',
    label: '管理员',
    description: '可管理团队信息与项目内容',
    members: teamStore.members.filter((member) => member.role === 'admin'),
  },
  {
    role: 'member',
    label: '成员',
    description: '可参与团队项目与 Skill 协作',
    members: teamStore.members.filter((member) => member.role === 'member'),
  },
].filter((group) => group.members.length))

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
          <AppEmptyState
            v-else
            :image="teamEmptyImg"
            title="暂无 Skill"
            description="可添加 Skill，开始构建并丰富团队共享技能库"
          />
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
              <div class="project-head">
                <div class="project-title-group">
                  <h4 class="project-title">{{ project.name }}</h4>
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

          <AppEmptyState
            v-else
            :image="teamEmptyImg"
            title="暂无项目"
            description="可新建项目，开始组织并协作管理团队 Skill"
          />
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
              <template v-if="editingProfile">
                <button class="btn-text" :disabled="profileSaving" @click="cancelEditProfile">取消</button>
              </template>
            </div>
            <div
              v-if="canManageProjects"
              class="toolbar-actions team-action-menu"
              :class="{ 'owner-actions': isOwner }"
              aria-label="团队操作"
            >
              <button
                class="team-action-btn save"
                :disabled="!editingProfile || profileSaving"
                :title="
                  !editingProfile
                    ? '请先编辑团队信息'
                    : profileSaving
                      ? '保存中…'
                      : '保存团队信息'
                "
                :aria-label="profileSaving ? '保存中' : '保存团队信息'"
                @click="saveProfile"
              >
                <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M518.528 709.973333l121.258667-122.453333a32 32 0 0 0-0.426667-45.226667 31.146667 31.146667 0 0 0-44.373333 0l-67.157334 68.266667V404.906667a31.445333 31.445333 0 1 0-62.933333 0v205.653333l-67.157333-68.266667a31.146667 31.146667 0 0 0-44.373334 0 32.426667 32.426667 0 0 0 0 45.226667l120.832 122.453333a32.768 32.768 0 0 0 22.4 9.386667 32.725333 32.725333 0 0 0 21.973334-9.386667z m306.133333-324.864c9.941333-0.128 20.736-0.256 30.592-0.256 10.965333 0 19.413333 8.533333 19.413334 19.2v343.04c0 105.813333-85.333333 191.573333-190.08 191.573334H348.714667C238.506667 938.666667 149.333333 848.64 149.333333 737.706667V277.76C149.333333 171.946667 234.24 85.333333 339.84 85.333333h225.578667c10.581333 0 19.456 8.96 19.456 19.626667v137.386667c0 78.08 63.36 142.08 141.098666 142.506666 17.834667 0 33.834667 0.128 47.786667 0.256 10.794667 0.085333 20.352 0.170667 28.672 0.170667 5.973333 0 13.824-0.085333 22.229333-0.170667z m11.818667-62.293333c-34.688 0.128-75.648 0-105.088-0.298667-46.72 0-85.205333-38.826667-85.205333-86.058666V123.989333c0-18.346667 22.101333-27.52 34.688-14.250666l124.416 130.645333 45.696 48a20.352 20.352 0 0 1-14.506667 34.432z" fill="currentColor"></path>
                </svg>
              </button>
              <button
                v-if="isOwner"
                class="team-action-btn assign"
                title="给成员分配管理员 / 成员权限"
                aria-label="分配权限"
                @click="showAssignRole = true"
              >
                <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M85.333333 472.704c2.133333 99.712 8.106667 270.378667 8.96 289.152 3.029333 40.234667 18.432 80.896 42.410667 109.568 33.365333 40.277333 74.453333 58.197333 131.754667 58.197333 79.189333 0.426667 166.485333 0.426667 251.306666 0.426667 85.077333 0 167.68 0 237.44-0.426667 56.490667 0 98.858667-18.389333 131.84-58.197333 23.936-28.629333 39.338667-69.717333 41.514667-109.525333 0.853333-15.872 5.12-201.045333 7.68-289.194667H85.333333z" fill="currentColor" opacity=".4"></path>
                  <path d="M479.786667 656.384v55.210667a32 32 0 0 0 64 0v-55.210667a32 32 0 0 0-64 0z" fill="currentColor"></path>
                  <path d="M435.669333 621.056a32 32 0 0 1-35.285333 23.253333c-108.8-15.189333-212.864-53.76-300.672-111.786666A31.872 31.872 0 0 1 85.333333 505.813333V357.973333c0-89.6 73.045333-162.474667 162.858667-162.474666h83.925333a125.994667 125.994667 0 0 1 124.586667-110.08h110.165333a125.994667 125.994667 0 0 1 124.586667 110.08h84.352A162.645333 162.645333 0 0 1 938.24 357.973333v147.882667a32.128 32.128 0 0 1-14.336 26.709333c-87.978667 58.24-192.426667 97.024-301.994667 112.213334a32 32 0 0 1-35.413333-23.808 77.013333 77.013333 0 0 0-74.922667-57.770667c-35.925333 0-66.432 23.253333-75.904 57.898667zM566.869333 149.333333h-110.165333c-28.714667 0-52.693333 19.626667-59.861333 46.122667h229.845333a62.122667 62.122667 0 0 0-59.818667-46.08z" fill="currentColor"></path>
                </svg>
              </button>
              <button
                v-if="isOwner"
                class="team-action-btn danger"
                title="解散团队（不可恢复）"
                aria-label="解散团队"
                @click="askRemoveTeam"
              >
                <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M865.578667 223.701333c16.64 0 30.421333 13.781333 30.421333 31.317334v16.213333a31.146667 31.146667 0 0 1-30.421333 31.317333H158.464A31.146667 31.146667 0 0 1 128 271.232v-16.213333c0-17.536 13.824-31.317333 30.464-31.317334H282.88c25.258667 0 47.232-17.962667 52.906667-43.306666l6.528-29.098667C352.469333 111.658667 385.749333 85.333333 423.893333 85.333333h176.213334c37.717333 0 71.424 26.325333 81.152 63.872l6.954666 31.146667a54.613333 54.613333 0 0 0 52.949334 43.349333h124.416z m-63.189334 592.682667c12.970667-121.045333 35.712-408.618667 35.712-411.52a31.829333 31.829333 0 0 0-7.68-23.808 30.976 30.976 0 0 0-22.357333-9.984H216.32c-8.533333 0-16.682667 3.712-22.357333 9.984a33.706667 33.706667 0 0 0-8.106667 23.808l2.261333 27.605333c6.058667 75.221333 22.912 284.757333 33.834667 383.914667 7.68 73.045333 55.637333 118.954667 125.056 120.618667 53.589333 1.237333 108.8 1.664 165.205333 1.664 53.162667 0 107.093333-0.426667 162.346667-1.664 71.850667-1.237333 119.722667-46.336 127.872-120.618667z" fill="currentColor"></path>
                </svg>
              </button>
              <button
                class="team-action-btn edit"
                :disabled="editingProfile"
                :title="editingProfile ? '正在编辑团队信息' : '编辑团队名称与描述'"
                aria-label="编辑团队名称与描述"
                @click="startEditProfile"
              >
                <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M400.042667 854.528l374.912-484.821333c20.352-26.112 27.605333-56.32 20.821333-87.125334-5.888-27.989333-23.082667-54.613333-48.896-74.752L683.946667 157.824c-54.784-43.562667-122.709333-38.997333-161.664 11.008l-42.069334 54.613333a16.128 16.128 0 0 0 2.688 22.442667l108.672 87.125333c7.253333 6.912 12.672 16.085333 14.08 27.093334a40.32 40.32 0 0 1-34.901333 44.458666 36.096 36.096 0 0 1-27.605333-7.765333l-111.829334-89.002667a13.354667 13.354667 0 0 0-18.133333 2.304L147.413333 654.08c-17.194667 21.546667-23.082667 49.536-17.194666 76.586667l33.962666 147.242666a17.066667 17.066667 0 0 0 16.725334 13.312l149.418666-1.834666a89.770667 89.770667 0 0 0 69.717334-34.858667z m209.237333-45.866667h243.626667c23.765333 0 43.093333 19.626667 43.093333 43.690667 0 24.106667-19.328 43.648-43.093333 43.648h-243.626667c-23.765333 0-43.093333-19.541333-43.093333-43.648s19.328-43.690667 43.093333-43.690667z" fill="currentColor"></path>
                </svg>
              </button>
            </div>
          </div>

          <div class="manage-stack">
            <!-- 团队信息：沿用团队项目「基本信息」的标签 + 浅底字段结构 -->
            <section class="manage-section" aria-labelledby="team-info-title">
              <header class="manage-section-heading">
                <div>
                  <h2 id="team-info-title">团队信息</h2>
                </div>
              </header>

              <div class="team-detail-form">
                <div class="team-detail-field">
                  <span class="team-detail-label">团队描述</span>
                  <div v-if="!editingProfile" class="team-detail-surface team-description">
                    {{ teamStore.currentTeam.description || '暂无描述' }}
                  </div>
                  <input
                    v-else
                    v-model="editDesc"
                    class="team-detail-surface team-detail-edit"
                    maxlength="200"
                    placeholder="一句话介绍团队职责"
                    @keyup.enter="saveProfile"
                  />
                </div>

                <div class="team-detail-grid">
                  <div class="team-detail-field">
                    <span class="team-detail-label">邀请码</span>
                    <div class="team-detail-surface">
                      <code class="invite-code">{{ teamStore.currentTeam.invite_code }}</code>
                    </div>
                  </div>
                  <div class="team-detail-field">
                    <span class="team-detail-label">Skill 自动热更新</span>
                    <div class="team-detail-surface setting-surface">
                      <label class="setting-toggle">
                        <input
                          type="checkbox"
                          :checked="teamStore.currentTeam.auto_skill_hot_update"
                          :disabled="settingsSaving"
                          @change="toggleAutoHotUpdate"
                        />
                        <span class="toggle-track" aria-hidden="true">
                          <span class="toggle-thumb"></span>
                        </span>
                        <span class="toggle-copy">
                          {{ teamStore.currentTeam.auto_skill_hot_update ? '已开启' : '已关闭' }}
                        </span>
                      </label>
                    </div>
                  </div>
                </div>
              </div>
            </section>

            <!-- 团队成员：按权限层级分组，并以团队项目同风格卡片展示 -->
            <section class="manage-section" aria-labelledby="team-members-title">
              <header class="manage-section-heading">
                <div>
                  <h2 id="team-members-title">
                    团队成员
                    <span class="member-count">{{ teamStore.members.length }}</span>
                  </h2>
                </div>
              </header>

              <div v-if="memberGroups.length" class="member-groups">
                <section
                  v-for="group in memberGroups"
                  :key="group.role"
                  class="member-group"
                  :class="`member-group-${group.role}`"
                >
                  <div class="member-group-heading">
                    <div>
                      <h3>{{ group.label }}</h3>
                    </div>
                    <span>{{ group.members.length }} 人</span>
                  </div>
                  <div class="member-card-grid">
                    <article
                      v-for="m in group.members"
                      :key="m.user_id"
                      class="member-card"
                      :class="`member-card-${m.role}`"
                    >
                      <div class="member-card-head">
                        <UserAvatar
                          class="member-avatar"
                          :name="m.display_name || m.username"
                          :src="m.avatar_url"
                          :size="30"
                        />
                        <div class="member-identity">
                          <strong>{{ m.display_name || m.username }}</strong>
                          <span v-if="m.display_name && m.username">@{{ m.username }}</span>
                        </div>
                        <span class="member-role" :class="`role-${m.role}`">
                          {{ roleLabel(m.role) }}
                        </span>
                      </div>
                      <p class="member-permission-copy">{{ group.description }}</p>
                    </article>
                  </div>
                </section>
              </div>
              <div v-else class="member-empty">暂无成员</div>
            </section>
          </div>
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
      <p class="assign-hint">仅所有者可调整成员角色。管理员可编辑团队信息。</p>
      <ul class="assign-list">
        <li v-for="m in teamStore.members" :key="m.user_id" class="assign-row">
          <UserAvatar
            class="member-avatar"
            :name="m.display_name || m.username"
            :src="m.avatar_url"
            :size="30"
          />
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

/* 团队管理操作：与项目操作一致的浅灰图标菜单。 */
.toolbar-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.team-action-menu {
  --base-menu-width: 156px;
  width: var(--base-menu-width);
  height: 58px;
  padding: 4px 8px;
  gap: 0;
  box-sizing: border-box;
  border-radius: 12px;
  background: #f1f3f5;
  transition: width 0.2s ease-in;
}

.team-action-menu.owner-actions {
  --base-menu-width: 296px;
}

.team-action-menu:has(.team-action-btn.assign:hover),
.team-action-menu:has(.team-action-btn.assign:focus-visible) {
  width: calc(var(--base-menu-width) + 62px);
}

.team-action-menu:has(.team-action-btn.danger:hover),
.team-action-menu:has(.team-action-btn.danger:focus-visible) {
  width: calc(var(--base-menu-width) + 62px);
}

.team-action-menu:has(.team-action-btn.edit:hover),
.team-action-menu:has(.team-action-btn.edit:focus-visible) {
  width: calc(var(--base-menu-width) + 32px);
}

.team-action-menu:has(.team-action-btn.save:hover),
.team-action-menu:has(.team-action-btn.save:focus-visible) {
  width: calc(var(--base-menu-width) + 32px);
}

.team-action-btn {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  width: 70px;
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
  transition: width 0.2s ease-in, background-color 0.2s ease-in, color 0.2s ease-in;
}

.team-action-btn.assign:hover,
.team-action-btn.assign:focus-visible {
  width: 132px;
  background: #e8e7ff;
}

.team-action-btn.danger:hover,
.team-action-btn.danger:focus-visible {
  width: 132px;
  background: #fee2e2;
}

.team-action-btn.edit:hover,
.team-action-btn.edit:focus-visible,
.team-action-btn.save:hover,
.team-action-btn.save:focus-visible {
  width: 102px;
}

.team-action-btn.edit:hover,
.team-action-btn.edit:focus-visible {
  background: #e2e5e9;
}

.team-action-btn.save:hover,
.team-action-btn.save:focus-visible {
  background: #dbeefe;
}

.team-action-btn:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 2px;
}

.team-action-btn::before {
  position: absolute;
  top: 50%;
  right: 8px;
  left: 48px;
  color: currentColor;
  font-size: 14px;
  font-weight: 600;
  text-align: center;
  white-space: nowrap;
  opacity: 0;
  transform: translate(100%, -50%);
  transition: transform 0.2s ease-in, opacity 0.2s ease-in;
}

.team-action-btn.assign::before {
  content: '分配权限';
}

.team-action-btn.danger::before {
  content: '解散团队';
}

.team-action-btn.edit::before {
  content: '编辑';
  letter-spacing: 0.18em;
}

.team-action-btn.save::before {
  content: '保存';
  letter-spacing: 0.18em;
}

.team-action-btn:hover::before,
.team-action-btn:focus-visible::before {
  opacity: 1;
  transform: translate(0, -50%);
}

.team-action-btn svg {
  position: absolute;
  left: 21px;
  width: 28px;
  height: 28px;
  display: block;
  flex-shrink: 0;
}

.team-action-btn.assign {
  color: #4f46e5;
}

.team-action-btn.danger {
  color: #dc2626;
}

.team-action-btn.edit {
  color: #151717;
}

.team-action-btn.save {
  color: #0284c7;
}

.team-action-btn:disabled {
  opacity: 0.42;
  cursor: not-allowed;
}

.manage-error {
  margin-bottom: 16px;
}

/* 团队管理：信息与成员上下排列，信息结构对齐团队项目「基本信息」 */
.manage-stack {
  display: flex;
  flex-direction: column;
  gap: 34px;
}

.manage-section {
  min-width: 0;
}

.manage-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.manage-section-heading h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
  color: #151717;
  font-size: 1.05rem;
  font-weight: 700;
  line-height: 1.4;
}

.member-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  min-width: 22px;
  height: 20px;
  padding: 0 7px;
  border-radius: 999px;
  background: #eef0f3;
  color: #606873;
  font-size: 0.72rem;
  font-weight: 600;
}

.team-detail-form {
  width: 100%;
}

.team-detail-field + .team-detail-field {
  margin-top: 14px;
}

.team-detail-label {
  display: block;
  margin-bottom: 6px;
  color: #606873;
  font-size: 0.78rem;
  font-weight: 500;
}

.team-detail-surface {
  display: flex;
  align-items: center;
  width: 100%;
  min-height: 40px;
  padding: 10px 12px;
  border: 1px solid transparent;
  border-radius: 7px;
  background: #eef0f3;
  color: #4b5563;
  font-family: inherit;
  font-size: 0.86rem;
  line-height: 1.55;
  box-sizing: border-box;
  word-break: break-word;
}

.team-description {
  min-height: 88px;
  align-items: flex-start;
}

.team-detail-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 14px;
  margin-top: 14px;
}

.team-detail-grid .team-detail-field {
  margin-top: 0;
}

.team-detail-edit {
  outline: none;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.team-detail-edit:focus {
  border-color: #151717;
  background: #ffffff;
}

.invite-code {
  color: #4b5563;
  font-size: 0.82rem;
  font-family: 'JetBrains Mono', monospace;
  letter-spacing: 0.02em;
}

.setting-surface {
  justify-content: space-between;
}

.setting-toggle {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 0.88rem;
  color: #30343b;
  cursor: pointer;
}

.setting-toggle input {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
}

.toggle-track {
  position: relative;
  width: 36px;
  height: 20px;
  flex-shrink: 0;
  border-radius: 999px;
  background: #c9cdd3;
  transition: background 0.18s ease;
}

.toggle-thumb {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 1px 3px rgba(21, 23, 23, 0.22);
  transition: transform 0.18s ease;
}

.setting-toggle input:checked + .toggle-track {
  background: #151717;
}

.setting-toggle input:checked + .toggle-track .toggle-thumb {
  transform: translateX(16px);
}

.setting-toggle input:focus-visible + .toggle-track {
  outline: 2px solid rgba(21, 23, 23, 0.22);
  outline-offset: 2px;
}

.setting-toggle input:disabled + .toggle-track,
.setting-toggle input:disabled ~ .toggle-copy {
  opacity: 0.55;
}

.setting-toggle:has(input:disabled) {
  cursor: not-allowed;
}

.member-groups {
  display: flex;
  flex-direction: column;
  gap: 22px;
}

.member-group-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.member-group-heading h3 {
  margin: 0;
  color: #30343b;
  font-size: 0.88rem;
  font-weight: 650;
}

.member-group-heading > span {
  flex-shrink: 0;
  color: #8b929b;
  font-size: 0.74rem;
}

.member-card-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}

.member-card {
  position: relative;
  min-width: 0;
  min-height: 118px;
  padding: 18px 20px;
  overflow: hidden;
  border: 2px solid #d7dae0;
  border-radius: 16px;
  background: #ffffff;
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.member-card:hover {
  border-color: #aeb4bd;
  box-shadow: 0 8px 24px rgba(21, 23, 23, 0.07);
}

.member-card-owner {
  border-color: #ead7a8;
}

.member-card-owner:hover {
  border-color: #d6a84c;
}

.member-card-admin {
  border-color: #d9d7f5;
}

.member-card-admin:hover {
  border-color: #8b83df;
}

.member-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
}

.member-identity {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.member-identity strong {
  overflow: hidden;
  color: #151717;
  font-size: 0.9rem;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-identity span {
  overflow: hidden;
  color: #9aa0a8;
  font-size: 0.74rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.member-permission-copy {
  margin: 14px 0 0;
  padding-top: 12px;
  border-top: 1px solid #eef0f2;
  color: #8b929b;
  font-size: 0.76rem;
  line-height: 1.45;
}

@media (max-width: 760px) {
  .team-detail-grid {
    grid-template-columns: 1fr;
  }

  .member-card-grid {
    grid-template-columns: 1fr;
  }
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
  transition: border-color 0.18s ease, box-shadow 0.18s ease;
}

.project-card:hover {
  border-color: var(--card-border-hover);
  box-shadow: 0 8px 24px rgba(21, 23, 23, 0.07);
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

.empty-hint {
  text-align: center;
  color: #9ca3af;
  font-size: 0.84rem;
  margin-top: 32px;
}

.empty-hint.load-error {
  color: #b45309;
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
