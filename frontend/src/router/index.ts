import { createRouter, createWebHashHistory } from 'vue-router'
import { getToken } from '@/runtime/tokenStorage'
import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { useTeamStore } from '@/stores/teamStore'

const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/Login.vue'),
      meta: { guest: true },
    },
    {
      path: '/onboarding',
      name: 'onboarding',
      component: () => import('@/views/Onboarding.vue'),
    },
    {
      path: '/',
      name: 'dashboard',
      component: () => import('@/views/Dashboard.vue'),
    },
    {
      // 团队工作台：与全局 AppTopNav 共用外壳，标签页由路由驱动。
      path: '/team/skills',
      name: 'team-skills',
      component: () => import('@/views/TeamWorkspace.vue'),
    },
    {
      path: '/team/projects',
      name: 'team-projects',
      component: () => import('@/views/TeamWorkspace.vue'),
    },
    {
      path: '/team/manage',
      name: 'team-manage',
      component: () => import('@/views/TeamWorkspace.vue'),
    },
    {
      path: '/projects/:id',
      name: 'project-skills',
      component: () => import('@/views/ProjectSkills.vue'),
    },
    {
      path: '/skills/:id',
      name: 'skill-detail',
      component: () => import('@/views/SkillDetail.vue'),
    },
    {
      path: '/skill-forge',
      name: 'skill-forge',
      component: () => import('@/views/SkillForge.vue'),
    },
    {
      // SKILL 市场：全局页（个人/团队空间共用），所有登录用户可见。
      path: '/market',
      name: 'skill-market',
      component: () => import('@/views/SkillMarket.vue'),
    },
    {
      // 市场条目只读「SKILL 介绍」详情页。
      path: '/market/:id',
      name: 'market-skill-detail',
      component: () => import('@/views/MarketSkillDetail.vue'),
    },
  ],
})

router.beforeEach(async (to, _from, next) => {
  const token = getToken()
  // 未登录：仅放行 guest 页（登录/注册）
  if (!to.meta?.guest && !token) {
    return next('/login')
  }
  // 已登录访问 guest 页 → 回主页
  if (to.meta?.guest && token) {
    return next('/')
  }

  // 首次登录引导：web 与桌面端均启用
  if (token) {
    const auth = useAuthStore()
    // 会话恢复时 user 可能尚未就绪（init 超时兜底），尽力补取一次
    if (!auth.user) {
      await auth.fetchMe()
    }
    const onboarded = auth.user?.onboarded
    if (to.path === '/onboarding') {
      // 已完成引导统一回主页，刷新时不再重复进入初始引导页。
      if (onboarded) return next('/')
      return next()
    }
    // 未完成引导 → 强制进入引导（user 取不到时不阻断，安全放行）
    if (auth.user && !onboarded) {
      return next('/onboarding')
    }

    // 首屏落点统一在此决策（唯一入口），避免落点逻辑散落多处反复打架：
    //  - 个人空间 → 留在 '/'（个人仓库）。
    //  - 团队空间 → 仅当所选团队“经校验确实存在”时才进团队工作台；
    //    否则（新用户/团队失效/残留状态）回退个人空间并留在 '/'，绝不展示不存在的团队页。
    if (to.path === '/') {
      const workspace = useWorkspaceStore()
      workspace.init()
      if (workspace.spaceType === 'team') {
        const teamStore = useTeamStore()
        if (!teamStore.teams.length) {
          await teamStore.fetchTeams()
        }
        const valid =
          !!workspace.activeTeamId &&
          teamStore.teams.some((t) => t.id === workspace.activeTeamId)
        if (valid) {
          return next('/team/skills')
        }
        workspace.switchToPersonal()
      }
    }
  }

  return next()
})

export default router
