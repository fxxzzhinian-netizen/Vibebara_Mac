<script setup lang="ts">
import { ref, computed, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useTeamStore } from '@/stores/teamStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { generateApiKey, getApiKeyStatus } from '@/api/auth'
import { toast } from '@/composables/useToast'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { useSlideIndicator } from '@/composables/useSlideIndicator'
import BaseModal from '@/components/BaseModal.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import ProfileDrawer from '@/views/Profile.vue'
import { getDesktopBridge, isDesktop } from '@/runtime/desktopBridge'
import { getRuntimeConfig } from '@/runtime/config'
import logoUrl from '@/img/logo.png'
import logoIconUrl from '@/img/logo_icon.png'

// 桌面壳（Electron）下隐藏了原生标题栏，顶栏需充当窗口拖动区，并为右上角原生窗口按钮留白。
const desktop = isDesktop()
// 开发服务器中保留桌面专属入口，便于在浏览器里调整 UI；生产 Web 端仍隐藏。
const showDesktopUpdateAction = desktop || import.meta.env.DEV

// 全局顶部导航：左 logo / 中分选栏 / 右头像（点击展开：用户信息 + 空间切换 + 退出）。
// 浅色（白底）风格，三栏栅格布局，分选栏与左右内容同一中心线对齐。

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()
const teamStore = useTeamStore()
const workspace = useWorkspaceStore()

const userMenuOpen = ref(false)
const userMenuRef = ref<HTMLElement | null>(null)
// 「空间选择」二级面板：桌面端悬停展开（CSS），触屏 / 点击端点击切换展开。
const spaceMenuOpen = ref(false)
// 中间搜索栏输入（聚焦时展开宽度）。
const searchQuery = ref('')
const cliAuthorizing = ref(false)
const cliKeyModalOpen = ref(false)
const generatedCliKey = ref('')
const hasCliApiKey = ref(false)
const cliHelpOpen = ref(false)
const updateChecking = ref(false)
const profileDrawerOpen = ref(false)
const profileDrawerRef = ref<InstanceType<typeof ProfileDrawer> | null>(null)
const cliActionLabel = computed(() => {
  if (cliAuthorizing.value) {
    return hasCliApiKey.value ? '正在轮换…' : '正在生成…'
  }
  return hasCliApiKey.value ? '轮换 CLI API Key' : '生成 CLI API Key'
})

// 中间导航项随当前空间动态变化：
//   个人空间 → SKILL 仓库 / SKILL 市场
//   团队空间 → 团队 SKILL / 团队项目 / 团队管理 / SKILL 市场
type NavIcon = 'repo' | 'market' | 'skill' | 'project'
type NavLink = { label: string; to?: string; reserved?: boolean; icon: NavIcon }
const navLinks = computed<NavLink[]>(() => {
  if (workspace.spaceType === 'team') {
    return [
      { label: '团队 SKILL', to: '/team/skills', icon: 'skill' },
      { label: '团队项目', to: '/team/projects', icon: 'project' },
      { label: '团队管理', to: '/team/manage', icon: 'project' },
      { label: 'SKILL 市场', to: '/market', icon: 'market' },
    ]
  }
  return [
    { label: 'SKILL 仓库', to: '/', icon: 'repo' },
    { label: 'SKILL 市场', to: '/market', icon: 'market' },
  ]
})

// 选中态白色滑块：测量当前 .active 分选项的位置/宽度，滑块平滑滑动过去。
// 触发源：路由变化（点选切页）与空间切换（个人/团队的分选项集合不同）。
const navLinksRef = ref<HTMLElement | null>(null)
const { style: navSliderStyle, ready: navSliderReady } = useSlideIndicator({
  container: navLinksRef,
  activeSelector: '.nav-item.active',
  axis: 'x',
  trigger: () => [route.path, workspace.spaceType],
  // 顶栏内嵌于每个页面、随路由整页重挂载；记忆上次位置，使跨页切换时白色胶囊
  // 从上一处平滑滑到当前项（如点击「SKILL 市场」）。
  memoryKey: 'top-nav',
})

function isLinkActive(link: NavLink) {
  if (link.reserved || !link.to) return false
  if (route.path === link.to) return true

  // 子页面保持所属分选栏高亮（如 Skill 编辑器、详情、平台结构、项目内页）
  if (link.to === '/') {
    if (route.path === '/skill-forge') return true
    if (workspace.spaceType === 'personal' && route.path.startsWith('/skills/')) return true
    return false
  }
  if (link.to === '/team/skills') {
    if (workspace.spaceType !== 'team') return false
    // 团队 Skill 详情归属「团队 SKILL」分选栏（'/' 由路由守卫保证只在个人空间渲染）
    return route.path.startsWith('/skills/')
  }
  if (link.to === '/team/projects') {
    return route.path.startsWith('/projects/')
  }
  return false
}

function goNav(link: NavLink) {
  if (link.reserved || !link.to) return
  if (route.path !== link.to) router.push(link.to)
}

function goHome() {
  // logo 跳转随空间走：团队空间回团队工作台，个人空间回个人仓库。
  if (workspace.spaceType === 'team' && workspace.activeTeamId) {
    router.push('/team/skills')
  } else {
    router.push('/')
  }
}

const displayName = computed(
  () => authStore.user?.display_name || authStore.user?.username || '未登录',
)
const accountIdentifier = computed(
  () => authStore.user?.email || (authStore.user?.username ? `@${authStore.user.username}` : ''),
)

function closeUserMenu() {
  userMenuOpen.value = false
  spaceMenuOpen.value = false
  cliHelpOpen.value = false
}

function toggleSpaceMenu() {
  spaceMenuOpen.value = !spaceMenuOpen.value
}

function pickPersonal() {
  workspace.switchToPersonal()
  closeUserMenu()
  router.push('/')
}

function pickTeam(teamId: string) {
  workspace.switchToTeam(teamId)
  closeUserMenu()
  // 进入团队 → 直接落到团队工作台（团队 SKILL 标签）
  router.push('/team/skills')
}

// —— 创建 / 加入团队（弹窗由本组件承载；开关挂在 teamStore 上，任意页面可唤起）——
const newTeamName = ref('')
const newTeamDesc = ref('')
const joinCode = ref('')

function openCreateTeam() {
  closeUserMenu()
  newTeamName.value = ''
  newTeamDesc.value = ''
  teamStore.openCreateModal()
}

function openJoinTeam() {
  closeUserMenu()
  joinCode.value = ''
  teamStore.openJoinModal()
}

async function submitCreateTeam() {
  if (!newTeamName.value.trim()) return
  const res = await teamStore.create(newTeamName.value.trim(), newTeamDesc.value.trim())
  if (res.success && teamStore.currentTeamId) {
    teamStore.createModalOpen = false
    workspace.switchToTeam(teamStore.currentTeamId)
    toast.success('团队已创建')
    router.push('/team/skills')
  } else if (!res.success) {
    toast.error(res.error || '创建失败')
  }
}

async function submitJoinTeam() {
  if (!joinCode.value.trim()) return
  const res = await teamStore.join(joinCode.value.trim())
  if (res.success && teamStore.currentTeamId) {
    teamStore.joinModalOpen = false
    workspace.switchToTeam(teamStore.currentTeamId)
    toast.success('已加入团队')
    router.push('/team/skills')
  } else if (!res.success) {
    toast.error(res.error || '加入失败')
  }
}

function toggleUserMenu() {
  if (userMenuOpen.value) {
    closeUserMenu()
  } else {
    userMenuOpen.value = true
  }
}

function goProfile() {
  closeUserMenu()
  profileDrawerOpen.value = true
}

async function openProfileAvatar() {
  closeUserMenu()
  profileDrawerOpen.value = true
  await nextTick()
  profileDrawerRef.value?.openAvatarDialog()
}

function logout() {
  closeUserMenu()
  authStore.logout()
  router.push('/login')
}

async function checkDesktopUpdate() {
  if (updateChecking.value) return
  const updater = getDesktopBridge()?.update
  if (!updater) {
    toast.warning('仅桌面客户端支持检查更新')
    return
  }

  updateChecking.value = true
  try {
    const state = await updater.check()
    if (state.status === 'error') {
      toast.error(state.message || '更新检查失败，请稍后重试')
    } else if (state.status === 'downloaded') {
      toast.success(`新版本 ${state.availableVersion || ''} 已下载，按提示重启即可安装`)
    } else if (['available', 'downloading'].includes(state.status)) {
      toast.info(`发现新版本 ${state.availableVersion || ''}，正在后台下载`)
    } else {
      toast.success(`当前已是最新版本 ${state.currentVersion}`)
    }
  } catch (error) {
    toast.error((error as Error)?.message || '更新检查失败，请稍后重试')
  } finally {
    updateChecking.value = false
  }
}

async function authorizeCli() {
  if (cliAuthorizing.value) return
  const rotating = hasCliApiKey.value
  closeUserMenu()
  const confirmed = await confirmDialog({
    title: rotating ? '轮换 CLI API Key' : '生成 CLI API Key',
    message: rotating
      ? '轮换后，当前 CLI、终端或 CI 中使用的旧 Key 会立即失效。'
      : '该长期凭证的明文仅在签发时返回一次，请妥善保存。',
    confirmText: rotating ? '确认轮换' : '确认生成',
    cancelText: '取消',
  })
  if (!confirmed) return

  cliAuthorizing.value = true
  try {
    const bridge = getDesktopBridge()
    const cloudApiBase = bridge ? getRuntimeConfig().cloudApiBase : ''
    if (bridge) {
      const parsed = new URL(cloudApiBase)
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        throw new Error('桌面云端地址无效，无法写入 CLI 配置')
      }
    }

    const issued = await generateApiKey()
    if (!issued.success || !issued.api_key) {
      throw new Error(issued.error || 'API Key 生成失败')
    }
    // 云端签发成功即视为已有凭证；即使后续桌面自动写盘失败，旧 Key 也已被轮换。
    hasCliApiKey.value = true

    if (bridge) {
      try {
        const result = await bridge.cli.authorize({
          apiKey: issued.api_key,
          cloudApiBase,
        })
        closeUserMenu()
        if (result.cliBundled) {
          toast.success('CLI 已授权；请重新打开终端后运行 vibebara whoami')
        } else {
          toast.success(
            `CLI 凭据已写入 ${result.configPath}；开发环境请先在 cli 目录运行 npm link`,
          )
        }
      } catch {
        // PAT 明文只返回一次；自动写盘失败时必须回显，避免刚轮换的 key 永久丢失。
        generatedCliKey.value = issued.api_key
        cliKeyModalOpen.value = true
        closeUserMenu()
        toast.error('自动写入失败，请复制 API Key 手动登录 CLI')
      }
    } else {
      generatedCliKey.value = issued.api_key
      cliKeyModalOpen.value = true
      closeUserMenu()
    }
  } catch (error) {
    toast.error((error as Error)?.message || 'CLI 授权失败')
  } finally {
    cliAuthorizing.value = false
  }
}

async function copyGeneratedCliKey() {
  try {
    await navigator.clipboard.writeText(generatedCliKey.value)
    toast.success('API Key 已复制')
  } catch {
    toast.error('复制失败，请手动复制')
  }
}

function selectGeneratedCliKey(event: FocusEvent) {
  const target = event.target as HTMLTextAreaElement | null
  target?.select()
}

function onClickOutside(e: MouseEvent) {
  if (userMenuRef.value && !userMenuRef.value.contains(e.target as Node)) {
    closeUserMenu()
  }
}

onMounted(async () => {
  workspace.init()
  document.addEventListener('click', onClickOutside)
  void getApiKeyStatus()
    .then((result) => {
      hasCliApiKey.value = result.success && result.has_api_key
    })
    .catch(() => {
      // 状态探测失败不阻塞菜单；真正生成时仍由受认证接口校验。
    })
  // 团队列表既是切换器选项，也用于校准持久化的选中团队是否仍有效。
  await teamStore.fetchTeams()
  workspace.ensureTeamValid(teamStore.teams)
})

onBeforeUnmount(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<template>
  <header :class="['top-nav', { 'is-desktop': desktop }]">
    <!-- 桌面壳：单独一条窗口标题栏，承载右上角原生窗口按钮 + 作为拖动区，避免挤压下方导航 -->
    <div v-if="desktop" class="win-bar" aria-hidden="true"></div>

    <div class="nav-inner">
      <!-- 左：logo -->
      <div class="nav-brand" @click="goHome">
        <img :src="logoUrl" alt="logo" class="brand-logo" />
        <img :src="logoIconUrl" alt="logo" class="brand-logo-compact" />
      </div>

      <!-- 中：分选栏（居中于视口中心线） -->
      <nav ref="navLinksRef" class="nav-links">
        <span class="nav-slider" :class="{ ready: navSliderReady }" :style="navSliderStyle"></span>
        <button
          v-for="link in navLinks"
          :key="link.label"
          :class="['nav-item', { active: isLinkActive(link), disabled: link.reserved }]"
          :aria-disabled="link.reserved || undefined"
          @click="goNav(link)"
        >
          <span class="nav-item-label">{{ link.label }}</span>
        </button>
      </nav>

      <!-- 右簇：搜索栏（靠近头像） + 头像 -->
      <div class="nav-right">
        <!-- 搜索栏：聚焦时向左展开宽度 -->
        <div class="container-input">
          <input
            v-model="searchQuery"
            type="text"
            placeholder="搜索"
            name="search"
            class="input"
          />
          <svg
            class="search-icon"
            width="18"
            height="18"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            xmlns="http://www.w3.org/2000/svg"
            aria-hidden="true"
          >
            <circle cx="11" cy="11" r="7" />
            <line x1="16.5" y1="16.5" x2="21" y2="21" />
          </svg>
        </div>

        <!-- 头像（点击展开：用户信息 + 空间切换 + 退出） -->
        <div ref="userMenuRef" class="user-menu">
        <button class="user-btn" :title="displayName" @click.stop="toggleUserMenu">
          <UserAvatar
            class="nav-user-avatar"
            :name="displayName"
            :src="authStore.user?.avatar_url"
            :size="42"
          />
        </button>

        <transition name="dropdown">
          <div v-if="userMenuOpen" class="dropdown user-dropdown">
            <section class="account-overview" aria-label="当前账号">
              <div class="account-overview-top">
                <span class="account-identifier">{{ accountIdentifier }}</span>
                <button
                  type="button"
                  class="account-overview-close"
                  aria-label="关闭账号菜单"
                  title="关闭"
                  @click.stop="closeUserMenu"
                >
                  ×
                </button>
              </div>

              <div class="account-avatar-wrap">
                <UserAvatar
                  class="account-overview-avatar"
                  :name="displayName"
                  :src="authStore.user?.avatar_url"
                  :size="82"
                />
                <button
                  type="button"
                  class="account-avatar-camera"
                  aria-label="更换个人头像"
                  title="更换个人头像"
                  @click.stop="openProfileAvatar"
                >
                  <svg viewBox="0 0 1024 1024">
                    <path d="M896.4 296.6l-0.1 0.1c-20.5-21.1-48.8-32.7-78.2-32.1h-96.2l-22.1-58.2c-6.3-14.5-16.5-27-29.5-36-12.9-9.8-28.5-15.4-44.6-16H404.8c-16 0.5-31.5 6.1-44.1 16-13.1 9-23.3 21.5-29.7 36l-24 58.2h-98.2c-29.4-0.6-57.7 11-78.2 32.1-21.1 20.5-32.7 48.8-32.1 78.1v386.9c-0.6 29.4 11 57.7 32.1 78.2 20.5 21.1 48.8 32.7 78.2 32.1h609.4c29.3 0.2 57.5-11.4 78.2-32.1 20.7-20.7 32.3-48.9 32.1-78.2V374.8c0.6-29.4-11-57.7-32.1-78.2zM513.5 743.7c-100.7 0-182.4-81.6-182.4-182.3 0-100.7 81.6-182.4 182.3-182.4 100.7 0 182.4 81.6 182.4 182.3-0.3 100.6-81.7 182.1-182.3 182.4z m0-302.7C445.8 441 391 495.9 391 563.5c0 67.7 54.9 122.5 122.5 122.5 67.7 0 122.5-54.9 122.5-122.5 0.3-32.6-12.5-63.9-35.6-86.9-23-23.1-54.3-35.9-86.9-35.6z" />
                  </svg>
                </button>
              </div>

              <p class="account-greeting">{{ displayName }}，您好！</p>
              <button type="button" class="manage-profile-btn" @click="goProfile">
                管理您的个人账号信息
              </button>
            </section>

            <div class="account-menu-divider" role="separator"></div>

            <!-- 空间选择：悬停（桌面）/ 点击（触屏）向左展开二级面板，再具体选择空间 -->
            <div :class="['submenu-wrap', { open: spaceMenuOpen }]">
              <button
                type="button"
                class="dropdown-item space-trigger"
                @click.stop="toggleSpaceMenu"
              >
                <span class="item-label">空间选择</span>
                <svg
                  class="submenu-caret"
                  width="14"
                  height="14"
                  viewBox="0 0 14 14"
                  fill="none"
                >
                  <path
                    d="M8.5 3.5L5 7l3.5 3.5"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </button>

              <div class="submenu">
                <div class="dropdown-section-title">切换空间</div>
                <button
                  :class="['dropdown-item', { selected: workspace.spaceType === 'personal' }]"
                  @click="pickPersonal"
                >
                  <span class="space-ico personal" aria-hidden="true">
                    <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
                      <path d="M877.373013 952.362426c-11.879562 0-21.537526-9.609869-21.537526-21.48943 0-91.825358-35.704177-178.166819-100.68412-243.09969-8.394181-8.394181-8.394181-22.032806-0.079818-30.426987 8.473999-8.394181 22.080901-8.394181 30.426987 0C858.569762 730.416522 898.814348 827.550793 898.814348 930.872996 898.814348 942.752558 889.252575 952.362426 877.373013 952.362426L877.373013 952.362426zM511.971859 587.042113c-91.873454 0-178.166819 35.767622-243.09969 100.732216-64.979944 64.931848-100.69947 151.273309-100.69947 243.09969 0 11.879562-9.561773 21.48943-21.441335 21.48943s-21.537526-9.609869-21.537526-21.48943c0-103.322204 40.212864-200.456475 113.331161-273.478582 72.990385-73.03848 170.108283-113.331161 273.446859-113.331161 11.879562 0 21.48943 9.609869 21.48943 21.48943S523.852444 587.042113 511.971859 587.042113L511.971859 587.042113zM512.004605 587.377758c-142.239562 0-257.873162-115.665323-257.873162-257.856789 0-142.159744 115.6336-257.873162 257.873162-257.873162 142.207839 0 257.873162 115.713418 257.873162 257.873162C769.877767 471.712435 654.211421 587.377758 512.004605 587.377758L512.004605 587.377758zM512.004605 114.626667c-118.479415 0-214.894302 96.414887-214.894302 214.894302 0 118.52751 96.414887 214.877929 214.894302 214.877929 118.447692 0 214.894302-96.350418 214.894302-214.877929C726.898907 211.041554 630.452297 114.626667 512.004605 114.626667L512.004605 114.626667z" fill="currentColor" />
                    </svg>
                  </span>
                  <span class="item-label">个人空间</span>
                  <svg
                    v-if="workspace.spaceType === 'personal'"
                    class="check"
                    width="14"
                    height="14"
                    viewBox="0 0 14 14"
                    fill="none"
                  >
                    <path
                      d="M2.5 7.5L5.5 10.5L11.5 3.5"
                      stroke="currentColor"
                      stroke-width="1.6"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                    />
                  </svg>
                </button>
                <template v-if="teamStore.teams.length">
                  <button
                    v-for="team in teamStore.teams"
                    :key="team.id"
                    :class="[
                      'dropdown-item',
                      {
                        selected:
                          workspace.spaceType === 'team' && workspace.activeTeamId === team.id,
                      },
                    ]"
                    @click="pickTeam(team.id)"
                  >
                    <span class="space-ico" aria-hidden="true">
                      <svg viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
                        <path d="M739.78368 268.9024c3.4816 12.47232 5.89824 25.14944 7.24992 37.94944 1.3312 12.5952 1.59744 25.21088 0.83968 37.84704-0.73728 12.47232-2.51904 24.80128-5.26336 37.02784-2.74432 12.12416-6.4512 23.9616-11.10016 35.49184-4.64896 11.55072-10.19904 22.67136-16.67072 33.32096-6.47168 10.71104-13.78304 20.82816-21.89312 30.39232-8.25344 9.66656-17.2032 18.57536-26.91072 26.78784a232.18176 232.18176 0 0 1-25.96864 19.0464c17.98144 6.06208 35.38944 13.39392 52.26496 21.95456 18.5344 9.37984 36.16768 20.15232 52.96128 32.31744 16.60928 12.02176 32.17408 25.27232 46.71488 39.71072 14.4384 14.35648 27.68896 29.75744 39.71072 46.16192 12.06272 16.42496 22.75328 33.64864 32.11264 51.712a387.72736 387.72736 0 0 1 38.56384 116.30592c3.39968 20.74624 5.12 41.65632 5.12 62.75072 0 3.91168-0.75776 7.65952-2.29376 11.22304-1.45408 3.46112-3.52256 6.51264-6.22592 9.15456a28.65152 28.65152 0 0 1-9.23648 6.16448 28.73344 28.73344 0 0 1-11.30496 2.27328c-3.91168 0-7.65952-0.75776-11.264-2.27328-3.4816-1.45408-6.5536-3.50208-9.25696-6.16448-2.6624-2.64192-4.75136-5.69344-6.22592-9.15456a28.42624 28.42624 0 0 1-2.29376-11.22304c0-22.71232-2.2528-45.11744-6.81984-67.1744-4.42368-21.504-10.9568-42.37312-19.53792-62.58688-8.47872-19.84512-18.80064-38.7072-30.96576-56.6272-12.0832-17.75616-25.74336-34.2016-41.00096-49.3568-15.27808-15.1552-31.82592-28.73344-49.70496-40.73472-18.0224-12.0832-37.02784-22.34368-57.01632-30.74048-20.35712-8.56064-41.3696-15.03232-63.01696-19.43552a338.458624 338.458624 0 0 0-67.6864-6.77888c-22.89664 0-45.44512 2.2528-67.6864 6.77888a333.830144 333.830144 0 0 0-63.01696 19.43552c-19.98848 8.3968-38.99392 18.65728-57.01632 30.74048a337.512448 337.512448 0 0 0-49.70496 40.73472c-15.2576 15.1552-28.91776 31.62112-41.00096 49.3568a333.279232 333.279232 0 0 0-30.96576 56.6272c-8.6016 20.21376-15.11424 41.08288-19.5584 62.58688a331.97056 331.97056 0 0 0-6.81984 67.1744c0 2.53952-0.32768 5.05856-1.00352 7.51616-0.63488 2.41664-1.59744 4.7104-2.8672 6.88128a28.44672 28.44672 0 0 1-4.54656 5.91872c-1.82272 1.82272-3.85024 3.35872-6.10304 4.64896-2.23232 1.26976-4.58752 2.2528-7.08608 2.92864a28.545024 28.545024 0 0 1-14.86848 0c-2.47808-0.67584-4.83328-1.6384-7.04512-2.90816-2.23232-1.26976-4.28032-2.78528-6.10304-4.608-1.80224-1.76128-3.31776-3.76832-4.58752-5.9392a28.2624 28.2624 0 0 1-2.8672-6.90176c-0.67584-2.4576-1.024-4.99712-1.024-7.53664 0.04096-21.13536 1.78176-42.06592 5.20192-62.83264 3.35872-20.41856 8.31488-40.42752 14.86848-60.08832 6.47168-19.39456 14.45888-38.15424 23.90016-56.36096 9.4208-18.06336 20.15232-35.30752 32.256-51.73248 12.10368-16.42496 25.3952-31.82592 39.89504-46.16192 14.60224-14.45888 30.208-27.68896 46.85824-39.71072a393.23648 393.23648 0 0 1 53.16608-32.27648c16.91648-8.54016 34.4064-15.85152 52.4288-21.89312-9.09312-5.75488-17.7152-12.0832-25.9072-19.02592-9.70752-8.21248-18.67776-17.12128-26.89024-26.78784-8.13056-9.56416-15.44192-19.68128-21.93408-30.39232-6.4512-10.6496-11.9808-21.77024-16.65024-33.32096a233.7792 233.7792 0 0 1-11.12064-35.49184c-2.7648-12.22656-4.52608-24.55552-5.28384-37.02784-0.75776-12.63616-0.49152-25.25184 0.83968-37.84704 1.3312-12.82048 3.76832-25.47712 7.24992-37.94944 3.4816-12.47232 7.94624-24.576 13.43488-36.2496 5.38624-11.48928 11.65312-22.46656 18.86208-32.91136 7.10656-10.32192 14.99136-20.00896 23.67488-29.06112 8.64256-9.03168 17.94048-17.28512 27.91424-24.82176a235.401216 235.401216 0 0 1 66.048-34.97984c12.04224-4.07552 24.35072-7.18848 36.92544-9.25696 12.8-2.12992 25.7024-3.19488 38.72768-3.19488 13.06624 0 25.96864 1.06496 38.76864 3.19488 12.57472 2.08896 24.90368 5.20192 36.94592 9.27744 11.91936 4.05504 23.40864 9.03168 34.52928 14.92992a234.55744 234.55744 0 0 1 31.51872 20.09088 234.2912 234.2912 0 0 1 27.87328 24.84224c8.68352 9.05216 16.56832 18.75968 23.67488 29.0816a231.768064 231.768064 0 0 1 32.21504 69.18144z m-127.75424 206.4384a175.777792 175.777792 0 0 0 47.08352-47.47264c6.28736-9.40032 11.61216-19.31264 15.9744-29.71648a172.11392 172.11392 0 0 0 9.99424-32.78848 174.022656 174.022656 0 0 0 3.33824-35.16416c-0.06144-11.89888-1.31072-23.59296-3.76832-35.1232a172.265472 172.265472 0 0 0-10.40384-32.6656 174.336 174.336 0 0 0-37.90848-55.23456c-7.9872-7.90528-16.6912-14.97088-26.05056-21.1968a175.992832 175.992832 0 0 0-29.9008-15.95392 175.302656 175.302656 0 0 0-32.99328-10.05568 179.912704 179.912704 0 0 0-35.4304-3.44064c-11.96032 0.04096-23.7568 1.26976-35.36896 3.66592a175.325184 175.325184 0 0 0-32.93184 10.26048 175.77984 175.77984 0 0 0-29.77792 16.13824 177.455104 177.455104 0 0 0-25.96864 21.34016 175.5136 175.5136 0 0 0-21.38112 25.82528 174.221312 174.221312 0 0 0-16.1792 29.65504 173.320192 173.320192 0 0 0-10.21952 32.72704 175.161344 175.161344 0 0 0-3.54304 35.14368c0 11.59168 1.14688 23.10144 3.44064 34.44736 2.27328 11.264 5.632 22.20032 10.07616 32.80896a172.476416 172.476416 0 0 0 16.32256 30.18752c6.51264 9.6256 13.9264 18.51392 22.2208 26.66496 8.31488 8.17152 17.32608 15.44192 27.07456 21.83168 9.66656 6.30784 19.8656 11.63264 30.59712 15.95392a174.104576 174.104576 0 0 0 33.11616 9.74848 174.292992 174.292992 0 0 0 34.67264 3.09248c11.9808-0.12288 23.7568-1.39264 35.34848-3.8912a173.883392 173.883392 0 0 0 32.8704-10.4448c10.40384-4.48512 20.29568-9.9328 29.696-16.34304z m358.17472-167.5264c2.51904 9.6256 4.17792 19.33312 5.03808 29.16352 0.83968 9.64608 0.88064 19.31264 0.1024 28.95872-0.77824 9.56416-2.29376 18.96448-4.62848 28.2624a176.39424 176.39424 0 0 1-9.07264 26.99264 176.05632 176.05632 0 0 1-13.35296 25.16992 177.32608 177.32608 0 0 1-17.34656 22.8352 173.879296 173.879296 0 0 1-21.15584 19.92704c-6.38976 5.09952-13.1072 9.728-20.15232 13.90592a283.4432 283.4432 0 0 1 28.13952 19.88608c10.19904 8.17152 19.7632 16.97792 28.73344 26.46016 8.88832 9.37984 17.08032 19.31264 24.59648 29.81888 7.49568 10.46528 14.2336 21.34016 20.23424 32.72704 6.00064 11.3664 11.20256 23.06048 15.60576 35.1232 4.4032 12.10368 7.9872 24.4736 10.69056 37.04832 2.7648 12.6976 4.62848 25.51808 5.59104 38.5024 0.98304 13.08672 1.04448 26.19392 0.18432 39.3216 0 3.87072-0.77824 7.5776-2.29376 11.12064-1.47456 3.46112-3.56352 6.51264-6.2464 9.15456-2.6624 2.6624-5.7344 4.7104-9.216 6.16448-3.60448 1.51552-7.3728 2.27328-11.30496 2.27328-3.93216 0-7.68-0.75776-11.264-2.27328-3.4816-1.45408-6.5536-3.50208-9.25696-6.16448a28.260352 28.260352 0 0 1-6.22592-9.15456 28.42624 28.42624 0 0 1-2.29376-11.22304c0-14.72512-0.98304-29.22496-2.94912-43.54048-2.02752-14.58176-5.0176-28.672-9.0112-42.25024-4.07552-13.94688-9.13408-27.09504-15.1552-39.48544-6.22592-12.8-13.37344-24.59648-21.48352-35.38944-8.3968-11.14112-17.7152-21.11488-27.91424-29.83936a173.971456 173.971456 0 0 0-34.52928-23.01952c-12.92288-6.53312-26.70592-11.4688-41.34912-14.82752-15.31904-3.52256-31.45728-5.26336-48.47616-5.26336-2.56 0-5.12-0.32768-7.59808-1.00352-2.43712-0.65536-4.75136-1.61792-6.94272-2.84672-2.19136-1.26976-4.1984-2.7648-5.98016-4.52608a28.49792 28.49792 0 0 1-7.61856-13.02528c-0.65536-2.41664-0.98304-4.9152-0.98304-7.41376a28.583936 28.583936 0 0 1 8.6016-20.41856c1.78176-1.76128 3.7888-3.2768 5.98016-4.52608 2.17088-1.24928 4.5056-2.21184 6.94272-2.8672 2.47808-0.65536 5.03808-0.98304 7.59808-0.98304h34.44736a119.748608 119.748608 0 0 0 46.42816-9.3184 119.078912 119.078912 0 0 0 52.44928-42.86464c4.32128-6.3488 7.96672-13.04576 10.97728-20.09088 3.072-7.168 5.36576-14.58176 6.94272-22.2208 1.61792-7.82336 2.41664-15.7696 2.41664-23.8592 0-8.06912-0.79872-16.01536-2.41664-23.8592-1.57696-7.61856-3.87072-15.03232-6.94272-22.20032a118.003712 118.003712 0 0 0-10.97728-20.09088 119.23456 119.23456 0 0 0-32.19456-31.96928c-6.41024-4.3008-13.14816-7.92576-20.25472-10.91584-7.22944-3.03104-14.70464-5.3248-22.36416-6.90176-7.90528-1.59744-15.93344-2.39616-24.064-2.39616-2.56 0-5.05856-0.32768-7.51616-1.00352a28.34432 28.34432 0 0 1-6.92224-2.84672 28.934144 28.934144 0 0 1-10.62912-10.5472c-1.31072-2.21184-2.27328-4.52608-2.92864-7.00416a28.3136 28.3136 0 0 1 0-14.80704c0.65536-2.4576 1.61792-4.79232 2.90816-6.98368 1.26976-2.21184 2.80576-4.23936 4.62848-6.02112 1.76128-1.78176 3.74784-3.2768 5.9392-4.54656 2.17088-1.24928 4.5056-2.19136 6.94272-2.84672 2.4576-0.67584 4.99712-1.00352 7.5776-1.00352 9.99424 0 19.8656 0.8192 29.67552 2.4576 9.60512 1.6384 19.00544 4.01408 28.24192 7.18848A177.922048 177.922048 0 0 1 907.14624 212.992c7.5776 5.81632 14.6432 12.20608 21.17632 19.1488 6.57408 7.00416 12.53376 14.45888 17.85856 22.4256 5.4272 8.06912 10.11712 16.50688 14.1312 25.35424 4.07552 9.0112 7.3728 18.28864 9.89184 27.89376z m-690.66752 186.49088c2.72384 2.72384 4.83328 5.85728 6.28736 9.37984 1.47456 3.52256 2.19136 7.18848 2.19136 11.03872v0.08192c-0.1024 3.7888-0.90112 7.3728-2.41664 10.81344-1.47456 3.33824-3.50208 6.32832-6.12352 8.88832a28.418048 28.418048 0 0 1-8.9088 6.06208c-3.4816 1.49504-7.12704 2.27328-10.97728 2.33472-16.9984 0-33.13664 1.76128-48.45568 5.28384-14.6432 3.35872-28.42624 8.27392-41.34912 14.80704a173.477888 173.477888 0 0 0-34.52928 23.04c-10.21952 8.72448-19.53792 18.67776-27.93472 29.83936-8.0896 10.79296-15.2576 22.56896-21.48352 35.38944-6.02112 12.3904-11.07968 25.53856-15.1552 39.48544-3.9936 13.57824-6.98368 27.66848-9.0112 42.25024-1.96608 14.29504-2.9696 28.81536-2.9696 43.54048 0 3.91168-0.75776 7.65952-2.27328 11.20256-1.47456 3.44064-3.54304 6.51264-6.22592 9.17504a29.650944 29.650944 0 0 1-9.25696 6.16448c-3.584 1.51552-7.33184 2.2528-11.28448 2.2528-3.93216 0-7.68-0.73728-11.28448-2.2528-3.4816-1.47456-6.5536-3.52256-9.23648-6.16448-2.6624-2.6624-4.77184-5.7344-6.22592-9.17504-1.51552-3.52256-2.29376-7.22944-2.31424-11.10016-0.86016-13.08672-0.79872-26.19392 0.18432-39.26016 0.96256-12.92288 2.80576-25.72288 5.55008-38.4 2.70336-12.57472 6.26688-24.8832 10.6496-36.98688a280.3712 280.3712 0 0 1 15.54432-35.06176 281.74336 281.74336 0 0 1 44.62592-62.44352c8.92928-9.46176 18.47296-18.26816 28.61056-26.4192 8.94976-7.168 18.28864-13.78304 28.03712-19.82464a180.441088 180.441088 0 0 1-20.19328-13.94688 177.199104 177.199104 0 0 1-21.15584-19.94752 176.074752 176.074752 0 0 1-30.72-48.00512 174.03904 174.03904 0 0 1-9.09312-26.97216 175.75936 175.75936 0 0 1-4.608-28.24192c-0.75776-9.64608-0.7168-19.29216 0.1024-28.95872 0.88064-9.8304 2.58048-19.5584 5.07904-29.14304 2.51904-9.60512 5.81632-18.88256 9.89184-27.91424 4.01408-8.82688 8.704-17.28512 14.1312-25.33376 5.3248-7.96672 11.28448-15.44192 17.85856-22.44608 6.5536-6.94272 13.59872-13.33248 21.17632-19.12832 7.5776-5.81632 15.58528-10.99776 23.98208-15.54432 8.4992-4.54656 17.26464-8.37632 26.35776-11.50976 9.23648-3.1744 18.6368-5.57056 28.24192-7.18848 9.78944-1.65888 19.68128-2.4576 29.65504-2.4576 3.95264 0 7.72096 0.73728 11.30496 2.2528 3.4816 1.45408 6.5536 3.50208 9.23648 6.16448 2.70336 2.64192 4.77184 5.69344 6.2464 9.15456 1.51552 3.56352 2.27328 7.31136 2.27328 11.22304 0 3.91168-0.75776 7.65952-2.27328 11.22304-1.47456 3.46112-3.54304 6.51264-6.2464 9.15456a28.65152 28.65152 0 0 1-9.23648 6.16448 28.73344 28.73344 0 0 1-11.30496 2.27328 119.330816 119.330816 0 0 0-46.40768 9.29792 117.755904 117.755904 0 0 0-20.25472 10.91584 119.001088 119.001088 0 0 0-17.63328 14.4384 117.796864 117.796864 0 0 0-14.56128 17.5104 119.576576 119.576576 0 0 0-10.97728 20.09088c-3.05152 7.168-5.36576 14.58176-6.94272 22.2208-1.61792 7.84384-2.43712 15.7696-2.43712 23.8592a117.608448 117.608448 0 0 0 20.35712 66.17088c4.28032 6.30784 9.13408 12.12416 14.56128 17.5104 5.4272 5.38624 11.30496 10.19904 17.63328 14.4384 6.41024 4.3008 13.14816 7.94624 20.25472 10.91584 7.22944 3.03104 14.68416 5.3248 22.38464 6.90176a120.832 120.832 0 0 0 24.02304 2.39616h34.44736c3.82976 0 7.53664 0.75776 11.14112 2.2528 3.52256 1.47456 6.656 3.54304 9.40032 6.2464z" fill="currentColor" />
                      </svg>
                    </span>
                    <span class="item-label">{{ team.name }}</span>
                    <svg
                      v-if="workspace.spaceType === 'team' && workspace.activeTeamId === team.id"
                      class="check"
                      width="14"
                      height="14"
                      viewBox="0 0 14 14"
                      fill="none"
                    >
                      <path
                        d="M2.5 7.5L5.5 10.5L11.5 3.5"
                        stroke="currentColor"
                        stroke-width="1.6"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                  </button>
                </template>
                <div v-else class="dropdown-empty">暂无团队</div>
                <div class="dropdown-divider"></div>
                <button class="dropdown-item team-action" @click="openCreateTeam">
                  <svg class="team-action-icon" viewBox="0 0 1026 1024" width="16" height="16" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                    <path d="M992 799.232h-192v191.808a32 32 0 1 1-64 0v-191.808h-192a32 32 0 1 1 0-63.936h192V543.488a32 32 0 0 1 64 0v191.808h192a32 32 0 1 1 0 63.936zM832 283.136C832 153.472 752.64 64 612.608 64H283.456C143.296 64 63.936 148.288 63.936 283.136v328.832c0 129.728 86.208 219.264 219.52 219.264h116.48v63.872H256C114.688 895.104 0 780.672 0 639.424V255.808A255.872 255.872 0 0 1 256 0h384c141.376 0 256 114.56 256 255.808v143.808h-64v-116.48z" fill="currentColor"></path>
                  </svg>
                  <span class="item-label">创建团队</span>
                </button>
                <button class="dropdown-item team-action" @click="openJoinTeam">
                  <svg class="team-action-icon" viewBox="0 0 1024 1024" width="16" height="16" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" stroke="currentColor" stroke-width="16" stroke-linejoin="round" stroke-linecap="round">
                    <path d="M619.008 65.536c-139.776 0-253.44 113.664-253.44 253.44 0 96.768 54.272 180.736 134.144 223.232-165.888 51.2-286.72 205.824-286.72 388.096 0 13.312 10.752 24.064 24.064 24.064 13.312 0 24.064-10.752 24.064-24.064 0-197.12 160.768-357.888 355.84-357.888 1.536 0 3.584-0.512 5.12-0.512 138.24-1.536 250.368-114.688 250.368-253.44C872.448 179.2 758.784 65.536 619.008 65.536zM619.008 523.776c-113.152 0-204.8-92.16-204.8-204.8 0-113.152 92.16-204.8 204.8-204.8 113.152 0 204.8 92.16 204.8 204.8C823.808 432.128 732.16 523.776 619.008 523.776z" fill="currentColor"></path>
                    <path d="M338.944 554.496c-155.136 0-281.6 134.144-281.6 299.52 0 13.312-10.752 24.064-24.064 24.064-13.312 0-24.064-10.752-24.064-24.064 0-153.088 94.72-283.648 225.28-329.728-61.44-37.888-102.912-108.032-102.912-188.416 0-120.32 93.184-218.624 207.36-218.624 13.312 0 24.064 10.752 24.064 24.064 0 13.312-10.752 24.064-24.064 24.064-87.552 0-159.232 76.288-159.232 169.984 0 93.696 71.168 169.984 159.232 169.984 13.312 0 24.064 10.752 24.064 24.064C363.008 543.744 352.256 554.496 338.944 554.496z" fill="currentColor"></path>
                    <path d="M986.624 798.72l-131.072 0 0 130.048c0 14.336-11.776 26.112-26.112 26.112-14.336 0-26.112-11.776-26.112-26.112L803.328 798.72l-131.072 0c-14.336 0-26.112-11.776-26.112-26.112 0-14.336 11.776-26.112 26.112-26.112l131.072 0 0-130.048c0-14.336 11.776-26.112 26.112-26.112 14.336 0 26.112 11.776 26.112 26.112l0 130.048 131.072 0c14.336 0 26.112 11.776 26.112 26.112C1012.736 786.944 1000.96 798.72 986.624 798.72z" fill="currentColor"></path>
                  </svg>
                  <span class="item-label">加入团队</span>
                </button>
              </div>
            </div>

            <div class="account-menu-divider" role="separator"></div>
            <div class="cli-auth-row">
              <button
                class="dropdown-item cli-auth"
                :disabled="cliAuthorizing"
                @click="authorizeCli"
              >
                <span class="item-label">{{ cliActionLabel }}</span>
              </button>
              <div :class="['cli-help-wrap', { open: cliHelpOpen }]">
                <button
                  type="button"
                  class="cli-help-tag"
                  :aria-expanded="cliHelpOpen"
                  aria-label="查看 CLI API Key 说明"
                  aria-describedby="cli-api-key-help"
                  @click.stop="cliHelpOpen = !cliHelpOpen"
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <circle cx="12" cy="12" r="9.5" />
                    <path d="M9.7 9a2.45 2.45 0 0 1 4.7.95c0 1.8-2.4 2.05-2.4 3.75" />
                    <circle class="cli-help-dot" cx="12" cy="17.1" r="0.8" />
                  </svg>
                </button>
                <div id="cli-api-key-help" class="cli-help-popover" role="tooltip" @click.stop>
                  <strong>CLI API Key</strong>
                  <p>用于在 Vibebara CLI 中登录你的账号，访问云端项目和 Skill。</p>
                  <p v-if="hasCliApiKey" class="cli-help-warning">
                    如果 Key 泄露或需要重新配置，可以轮换；之后请使用新 Key 重新登录 CLI。
                  </p>
                </div>
              </div>
            </div>
            <div class="account-menu-divider" role="separator"></div>
            <button
              v-if="showDesktopUpdateAction"
              type="button"
              class="dropdown-item desktop-update"
              :disabled="updateChecking"
              @click="checkDesktopUpdate"
            >
              <span class="item-label">
                {{ updateChecking ? '正在检查更新…' : '检查更新' }}
              </span>
              <svg
                class="desktop-update-icon"
                :class="{ spinning: updateChecking }"
                viewBox="0 0 1024 1024"
                aria-hidden="true"
              >
                <path
                  d="M195.264 828.8a48 48 0 0 1 28.16-81.664l218.752-26.688a48 48 0 1 1 11.712 95.168l-98.048 12.032a352 352 0 0 0 508.16-315.776 48 48 0 1 1 96 0 448 448 0 0 1-764.672 316.864zM64 512a448 448 0 0 1 764.672-316.736 48 48 0 0 1-28.224 81.664l-218.688 26.688a47.936 47.936 0 1 1-11.712-95.104l98.048-12.096a352.32 352.32 0 0 0-508.224 315.648 48 48 0 1 1-96 0z"
                />
              </svg>
            </button>
            <div
              v-if="showDesktopUpdateAction"
              class="account-menu-divider"
              role="separator"
            ></div>
            <button class="dropdown-item logout" @click="logout">退出登录</button>
          </div>
        </transition>
        </div>
      </div>
    </div>

    <ProfileDrawer ref="profileDrawerRef" v-model="profileDrawerOpen" />

    <!-- 创建团队弹窗 -->
    <BaseModal
      :model-value="teamStore.createModalOpen"
      title="创建团队"
      @update:model-value="teamStore.createModalOpen = $event"
    >
      <div class="field">
        <label>团队名称</label>
        <input v-model="newTeamName" placeholder="输入团队名称" @keyup.enter="submitCreateTeam" />
      </div>
      <div class="field">
        <label>描述（可选）</label>
        <input v-model="newTeamDesc" placeholder="团队描述" @keyup.enter="submitCreateTeam" />
      </div>
      <template #footer>
        <button class="btn-sm btn-primary" @click="submitCreateTeam">创建</button>
      </template>
    </BaseModal>

    <!-- 加入团队弹窗 -->
    <BaseModal
      :model-value="teamStore.joinModalOpen"
      title="加入团队"
      @update:model-value="teamStore.joinModalOpen = $event"
    >
      <div class="field">
        <label>邀请码</label>
        <input v-model="joinCode" placeholder="输入邀请码" @keyup.enter="submitJoinTeam" />
      </div>
      <template #footer>
        <button class="btn-sm btn-primary" @click="submitJoinTeam">加入</button>
      </template>
    </BaseModal>

    <BaseModal
      :model-value="cliKeyModalOpen"
      title="CLI API Key（仅显示一次）"
      @update:model-value="cliKeyModalOpen = $event"
    >
      <p class="cli-key-help">
        请运行 <code>vibebara login --api-key &lt;key&gt;</code>，或将密钥保存到 CI Secret。
      </p>
      <textarea
        class="cli-key-value"
        :value="generatedCliKey"
        readonly
        rows="4"
        @focus="selectGeneratedCliKey"
      ></textarea>
      <template #footer>
        <button class="btn-sm btn-primary" @click="copyGeneratedCliKey">复制 API Key</button>
      </template>
    </BaseModal>
  </header>
</template>

<style scoped>
.top-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  /* 导航栏与正文背景统一，扁平无分层 */
  background: var(--canvas);
}

/* 桌面壳（Electron 无边框窗口）：在导航栏上方单独叠一条窗口标题栏，
   仅承载右上角原生最小化/最大化/关闭按钮，并整条作为窗口拖动区。
   下方 .nav-inner 因此恢复整行宽度，不再被窗口按钮挤压右侧。
   高度需与主进程 titleBarOverlay.height 一致（见 desktop/src/main/index.ts）。 */
.win-bar {
  height: 40px;
  -webkit-app-region: drag;
}

.nav-inner {
  /* 三栏栅格：左 logo / 中分选栏 / 右(搜索+头像)。两侧 1fr 等宽，分选栏严格居于视口中心线。 */
  width: 100%;
  padding: 0 1.5rem;
  height: 84px;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  box-sizing: border-box;
}

/* 右簇：搜索栏 + 头像 */
.nav-right {
  justify-self: end;
  display: flex;
  align-items: center;
  gap: 1rem;
}

/* —— 左：品牌 —— */
.nav-brand {
  justify-self: start;
  display: flex;
  align-items: center;
  gap: 0.6rem;
  cursor: pointer;
  user-select: none;
}

.brand-logo {
  height: 30px;
  width: auto;
  display: block;
  /* 视觉上微调上移，校正 logo 图内留白带来的偏低观感 */
  transform: translateY(-5px);
}

.brand-logo-compact {
  display: none;
  width: 34px;
  height: 34px;
  object-fit: contain;
}

/* —— 中：分选栏（纯文字，无边框 / 无卡片，居中于视口中心线） —— */
.nav-links {
  position: relative;
  justify-self: center;
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

/* 选中态黑色胶囊滑块：绝对定位于分选项之下，随选中项平滑滑动 + 变宽。 */
.nav-slider {
  position: absolute;
  top: 0;
  bottom: 0;
  left: 0;
  width: 0;
  border-radius: 999px;
  background: #151717;
  box-shadow: 0 1px 3px rgba(21, 23, 23, 0.18);
  opacity: 0;
  z-index: 0;
  pointer-events: none;
  will-change: transform, width;
}

.nav-slider::after {
  content: '';
  position: absolute;
  inset: 3px;
  border: 2px solid rgba(255, 255, 255, 0.92);
  border-radius: inherit;
}

.nav-slider.ready {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1),
    width 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
}

.nav-item {
  position: relative;
  z-index: 1;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 保持紧凑宽度，并增加竖向留白以强化激活背景。 */
  width: 120px;
  box-sizing: border-box;
  padding: 0.72rem 0.84rem;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #5f6368;
  font-family: inherit;
  font-size: 1rem;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s ease, background 0.15s ease;
}

.nav-item-label {
  line-height: 1;
}

.nav-item:hover:not(.disabled):not(.active) {
  color: #202124;
  background: rgba(21, 23, 23, 0.05);
}

/* 选中项：白色加粗文字；黑色胶囊底由 .nav-slider 提供（可滑动） */
.nav-item.active {
  color: #ffffff;
  font-weight: 600;
}

.nav-item.disabled {
  cursor: default;
  color: #b0b4ba;
}

/* —— 中：搜索栏（聚焦展开宽度） —— */
.container-input {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.container-input .input {
  width: 150px;
  padding: 9px 14px 9px 38px;
  border-radius: 9999px;
  /* 边框加粗 */
  border: solid 2px #333;
  /* 磨砂玻璃：半透明白底 + 背景模糊 */
  background: rgba(255, 255, 255, 0.5);
  backdrop-filter: blur(14px) saturate(160%);
  -webkit-backdrop-filter: blur(14px) saturate(160%);
  color: #202124;
  font-family: inherit;
  font-size: 0.9rem;
  transition: width 0.2s ease-in-out, opacity 0.2s ease-in-out;
  outline: none;
  opacity: 0.85;
  box-sizing: border-box;
}

.container-input .input::placeholder {
  color: #9aa0a6;
}

.container-input .search-icon {
  position: absolute;
  top: 50%;
  left: 12px;
  transform: translateY(-50%);
  color: #333;
  pointer-events: none;
}

.container-input .input:focus {
  opacity: 1;
  width: 250px;
}

/* —— 空间图标（用于头像下拉里的空间切换项）：个人=单人(绿) / 团队=多人(主色紫) —— */
.space-ico {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 19px;
  height: 19px;
  flex-shrink: 0;
  color: var(--primary);
}

/* 个人空间：绿色 */
.space-ico.personal {
  color: #16a34a;
}

.space-ico svg {
  display: block;
  width: 100%;
  height: 100%;
}

/* 给描边风格图标补一层同色描边，整体略微加粗（个人/团队同量，粗细保持一致） */
.space-ico svg path {
  stroke: currentColor;
  stroke-width: 15;
  stroke-linejoin: round;
  stroke-linecap: round;
}

/* —— 下拉面板 —— */
.dropdown {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  min-width: 220px;
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 14px;
  box-shadow: 0 12px 32px rgba(21, 23, 23, 0.1);
  padding: 0.4rem;
  overflow: hidden;
}

.dropdown-section-title {
  padding: 0.4rem 0.7rem 0.25rem;
  font-size: 0.7rem;
  font-weight: 600;
  color: #9ca3af;
  letter-spacing: 0.05em;
}

.dropdown-item {
  display: flex;
  align-items: center;
  gap: 0.55rem;
  width: 100%;
  padding: 0.5rem 0.7rem;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease;
}

.dropdown-item:hover {
  background: #f6f7f8;
}

.dropdown-item.selected {
  font-weight: 600;
  background: #f1f3f4;
}

.item-label {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.check {
  color: #16a34a;
  flex-shrink: 0;
}

.dropdown-divider {
  height: 1px;
  background: #d9dfe7;
  margin: 0.3rem 0.4rem;
}

.dropdown-empty {
  padding: 0.5rem 0.7rem;
  font-size: 0.84rem;
  color: #9ca3af;
}

.dropdown-item.team-action {
  color: #6b7280;
  font-size: 0.84rem;
}

.dropdown-item.team-action:hover {
  color: #151717;
}

.team-action-icon {
  flex-shrink: 0;
  color: #9ca3af;
}

.dropdown-item.team-action:hover .team-action-icon {
  color: #151717;
}

.arrow {
  font-size: 0.84rem;
  color: #9ca3af;
}

/* —— 空间选择：二级飞出面板（悬停/触摸展开） —— */
.submenu-wrap {
  position: relative;
}

.space-trigger .submenu-caret {
  margin-left: auto;
  color: #9ca3af;
  flex-shrink: 0;
}

.submenu {
  position: absolute;
  top: -0.4rem;
  right: calc(100% + 14px);
  min-width: 200px;
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 14px;
  box-shadow: 0 12px 32px rgba(21, 23, 23, 0.12);
  padding: 0.4rem;
  opacity: 0;
  visibility: hidden;
  transform: translateX(8px);
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0s linear 0.15s;
  z-index: 10;
}

/* 透明悬停桥：覆盖父项与二级面板之间的 8px 间隙，避免移动途中丢失 hover。 */
.submenu::before {
  content: '';
  position: absolute;
  top: 0;
  left: 100%;
  width: 16px;
  height: 100%;
}

.submenu-wrap:hover .space-trigger,
.submenu-wrap.open .space-trigger {
  background: #e6ebf2;
}

.submenu .dropdown-item:not(.team-action):hover {
  background: #e8edf4;
}

.submenu .dropdown-item.team-action:hover {
  background: #f4f5f7;
}

.submenu > .dropdown-divider {
  height: 1.5px;
  background: #cbd3dd;
}

.submenu-wrap:hover .submenu,
.submenu-wrap.open .submenu {
  opacity: 1;
  visibility: visible;
  transform: translateX(0);
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0s;
}

/* —— 右：头像菜单 —— */
.user-menu {
  position: relative;
}

.user-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  /* 头像外侧一圈 Google 四色渐变环，环与内圆之间留白缝 */
  padding: 2.5px;
  border: none;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    #4285f4,
    #34a853,
    #fbbc05,
    #ea4335,
    #4285f4
  );
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.user-btn:hover {
  box-shadow: 0 2px 8px rgba(21, 23, 23, 0.18);
}

.nav-user-avatar {
  border: 2px solid #ffffff;
  box-sizing: content-box;
}

.user-dropdown {
  width: min(330px, calc(100vw - 24px));
  background: #eef3fb;
  /* 覆盖 .dropdown 的 overflow: hidden，否则向左飞出的二级面板会被裁切 */
  overflow: visible;
}

.account-overview {
  margin: -0.4rem -0.4rem 0.35rem;
  padding: 15px 18px 20px;
  border-radius: 14px 14px 20px 20px;
  background: transparent;
  text-align: center;
}

.account-overview-top {
  position: relative;
  min-height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.account-identifier {
  max-width: calc(100% - 56px);
  overflow: hidden;
  color: #303134;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.account-overview-close {
  position: absolute;
  top: -4px;
  right: -7px;
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #5f6368;
  font: inherit;
  font-size: 24px;
  line-height: 1;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.account-overview-close:hover,
.account-overview-close:focus-visible {
  background: rgba(60, 64, 67, 0.1);
  color: #202124;
  outline: none;
}

.account-avatar-wrap {
  position: relative;
  width: 90px;
  height: 90px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 10px;
  padding: 5px;
  border-radius: 50%;
  background: conic-gradient(
    from 0deg,
    #4285f4,
    #34a853,
    #fbbc05,
    #ea4335,
    #4285f4
  );
}

.account-overview-avatar {
  border: 3px solid #eef3fb;
  box-sizing: content-box;
}

.account-avatar-camera {
  position: absolute;
  right: -4px;
  bottom: 0;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: 3px solid #eef3fb;
  border-radius: 50%;
  background: #ffffff;
  color: #000000;
  font: inherit;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease, transform 0.15s ease;
}

.account-avatar-camera svg {
  width: 22px;
  height: 22px;
  fill: currentColor;
}

.account-avatar-camera:hover,
.account-avatar-camera:focus-visible {
  background: #000000;
  color: #ffffff;
  outline: none;
}

.account-avatar-camera:active {
  transform: scale(0.94);
}

.account-greeting {
  margin: 12px 0 14px;
  color: #202124;
  font-size: 20px;
  font-weight: 500;
  line-height: 1.4;
}

.manage-profile-btn {
  min-height: 38px;
  padding: 0 18px;
  border: 2px solid #005ea8;
  border-radius: 999px;
  background: #ffffff;
  color: #005ea8;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 1px 2px rgba(60, 64, 67, 0.08);
  transition: background 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}

.manage-profile-btn:hover,
.manage-profile-btn:focus-visible {
  background: #005ea8;
  color: #ffffff;
  box-shadow:
    inset 0 0 0 3px #eef3fb,
    0 1px 3px rgba(60, 64, 67, 0.15);
  outline: none;
}

.account-menu-divider {
  width: calc(100% - 12px);
  height: 0;
  flex: 0 0 auto;
  margin: 6px;
  border: 0;
  border-top: 1.5px solid rgba(60, 64, 67, 0.2);
}

.user-dropdown > .dropdown-item:hover,
.user-dropdown > .cli-auth-row > .dropdown-item:hover,
.user-dropdown > .submenu-wrap > .dropdown-item:hover,
.user-dropdown > .submenu-wrap.open > .dropdown-item {
  background: rgba(255, 255, 255, 0.78);
}

.dropdown-item.logout {
  color: #dc2626;
}

.dropdown-item.logout:hover {
  background: #fef2f2;
}

.cli-auth-row {
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
}

.dropdown-item.cli-auth {
  min-width: 0;
  flex: 1;
}

.user-dropdown > .submenu-wrap > .space-trigger,
.user-dropdown > .cli-auth-row > .cli-auth,
.user-dropdown > .desktop-update,
.user-dropdown > .logout {
  font-weight: 500;
}

.desktop-update-icon {
  width: 19px;
  height: 19px;
  flex-shrink: 0;
  margin-right: 4px;
  color: #687386;
  fill: currentColor;
}

.desktop-update-icon.spinning {
  animation: update-spin 0.8s linear infinite;
}

@keyframes update-spin {
  to {
    transform: rotate(360deg);
  }
}

.cli-help-wrap {
  position: relative;
  flex-shrink: 0;
  margin-right: 0.7rem;
}

.cli-help-tag {
  width: 26px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  border: none;
  border-radius: 50%;
  background: transparent;
  color: #687386;
  cursor: help;
  transition: background 0.15s ease, color 0.15s ease;
}

.cli-help-tag svg {
  width: 22px;
  height: 22px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.cli-help-tag .cli-help-dot {
  fill: currentColor;
  stroke: none;
}

.cli-help-tag:hover,
.cli-help-tag:focus-visible,
.cli-help-wrap.open .cli-help-tag {
  background: rgba(255, 255, 255, 0.72);
  color: #1f4f8f;
  outline: none;
}

.cli-help-popover {
  position: absolute;
  right: 0;
  bottom: calc(100% + 9px);
  z-index: 20;
  width: min(286px, calc(100vw - 48px));
  padding: 13px 14px;
  border: 1px solid #dfe5ed;
  border-radius: 10px;
  background: #ffffff;
  color: #3c4043;
  box-shadow: 0 10px 28px rgba(21, 23, 23, 0.16);
  font-size: 12px;
  font-weight: 400;
  line-height: 1.55;
  opacity: 0;
  visibility: hidden;
  transform: translateY(5px);
  pointer-events: none;
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0s linear 0.15s;
}

.cli-help-popover strong {
  display: block;
  margin-bottom: 5px;
  color: #202124;
  font-size: 13px;
}

.cli-help-popover p {
  margin: 0;
}

.cli-help-popover p + p {
  margin-top: 7px;
}

.cli-help-popover .cli-help-warning {
  color: #9a5a00;
}

.cli-help-wrap:hover .cli-help-popover,
.cli-help-wrap:focus-within .cli-help-popover,
.cli-help-wrap.open .cli-help-popover {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
  pointer-events: auto;
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0s;
}

.dropdown-item:disabled {
  cursor: wait;
  opacity: 0.55;
}

.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* —— 创建 / 加入团队弹窗 —— */
.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-size: 0.82rem;
  color: #6b7280;
  margin-bottom: 6px;
}

.field input {
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

.field input:focus {
  border-color: #151717;
  background: #ffffff;
}

.error-msg {
  color: #dc2626;
  font-size: 0.82rem;
  margin-bottom: 12px;
}

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

.btn-sm.btn-primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
  font-weight: 600;
}

.btn-sm.btn-primary:hover {
  background: #2d2f2f;
  border-color: #2d2f2f;
  color: #ffffff;
}

.cli-key-help {
  margin: 0 0 12px;
  color: #6b7280;
  font-size: 0.84rem;
  line-height: 1.6;
}

.cli-key-help code {
  color: #151717;
}

.cli-key-value {
  width: 100%;
  box-sizing: border-box;
  resize: none;
  padding: 10px 12px;
  border: 1px solid #dfe2e6;
  border-radius: 7px;
  background: #f6f7f8;
  color: #151717;
  font-family: ui-monospace, SFMono-Regular, Consolas, monospace;
  font-size: 0.78rem;
  line-height: 1.5;
  word-break: break-all;
}

@media (max-width: 980px) {
  .nav-inner {
    grid-template-columns: auto minmax(0, 1fr) auto;
    padding: 0 0.85rem;
    gap: 0.55rem;
  }

  .brand-logo {
    width: 116px;
    height: auto;
  }

  .nav-links {
    min-width: 0;
    gap: 0.15rem;
  }

  .nav-item {
    width: auto;
    min-width: 0;
    padding: 0.66rem 0.6rem;
    font-size: 0.88rem;
  }

  .container-input {
    display: none;
  }

  .nav-right {
    gap: 0.5rem;
  }
}

@media (max-width: 980px) {
  .brand-logo {
    display: none;
  }

  .brand-logo-compact {
    display: block;
  }

  .nav-item {
    padding-inline: 0.45rem;
    font-size: 0.82rem;
  }

  .nav-user-avatar {
    width: 36px !important;
    height: 36px !important;
  }
}
</style>
