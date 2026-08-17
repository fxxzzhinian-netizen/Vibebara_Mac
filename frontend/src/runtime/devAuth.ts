/**
 * 开发者模式：跳过登录直达 UI（仅用于本地调样式 / 调 UI）。
 *
 * 开启方式：在 `frontend/.env.local` 写入 `VITE_DEV_SKIP_AUTH=true`，再重启 `npm run dev`。
 *
 * 安全约束：仅当 `import.meta.env.DEV`（即 `vite dev`）且显式开启时才生效；
 * 生产构建（`vite build`）下 `import.meta.env.DEV` 为 false，本开关恒为关闭，
 * 不会被打进线上产物，杜绝误绕过鉴权。
 *
 * 行为：注入一个假 token + 假用户，让路由守卫判定为「已登录」，跳过登录页。
 * 注意：后端接口仍会因 token 非法返回 401（控制台可见报错），页面以「空数据」渲染
 * ——这对纯 UI/样式调试足够；需要真实数据时请关闭本开关正常登录。
 *
 * 假用户默认视为已完成引导，刷新后直接进入工作台，避免本地调试时反复经过初始页。
 */
import type { UserInfo } from '@/api/auth'

const env = import.meta.env as Record<string, string | undefined>

/** 是否启用「跳过登录」开发者模式（仅 dev 且显式开启）。 */
export const DEV_SKIP_AUTH =
  import.meta.env.DEV && env.VITE_DEV_SKIP_AUTH === 'true'

/** 开发者模式下注入的假 token（仅用于让守卫/拦截器判定为「已登录」）。 */
export const DEV_FAKE_TOKEN = 'dev-skip-auth'

/** 开发者模式下注入的假用户（默认已完成引导，直达工作台）。 */
export const DEV_FAKE_USER: UserInfo = {
  id: 'dev-user',
  username: 'dev',
  display_name: '开发者',
  email: null,
  avatar_url: null,
  phone: null,
  gender: null,
  birthday: null,
  locale: 'zh-CN',
  location: null,
  created_at: null,
  onboarded: true,
  dev_mode: null,
  favorite_tool: null,
  // dev 预览：放开市场审核 / 管理员入口，便于本地联调市场各分页
  is_platform_admin: true,
  is_seed_user: true,
  is_reviewer: true,
  can_manage_admins: true,
}
