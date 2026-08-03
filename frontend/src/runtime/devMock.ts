/**
 * 开发者模式假数据（仅用于本地调样式 / 调 UI）。
 *
 * 背景：开启 `VITE_DEV_SKIP_AUTH=true` 后注入的是假 token，后端所有接口都会以
 * 401 拒绝，页面只能渲染空数据，无法预览真实排版。本模块在 `DEV_SKIP_AUTH` 为真时
 * 为「Skill 仓库列表 / Skill 详情」提供一批假数据，让 Dashboard、SkillForge、
 * SkillDetail 能渲染出真实样式用于调试。
 *
 * 安全约束：所有导出仅应在 `DEV_SKIP_AUTH` 为真时被调用（见 api/skillStore.ts 的守卫），
 * 而 `DEV_SKIP_AUTH` 本身被 `import.meta.env.DEV` 锁死，生产构建恒为关闭，假数据不会
 * 进入线上产物。
 */
import type {
  NativeSkillItem,
  NativeSkillDetail,
  NativeSkillListResponse,
} from '@/api/skillStore'
import type {
  TeamInfo,
  TeamMemberInfo,
  TeamListResponse,
  TeamResponse,
  MemberListResponse,
} from '@/api/teams'
import type {
  ProjectInfo,
  ProjectListResponse,
  ProjectDetailResponse,
  ProjectResponse,
  ProjectSkillInfo,
  UserSkillDeploymentInfo,
} from '@/api/projects'

const NOW = '2026-06-10T08:00:00Z'

function makeItem(partial: Partial<NativeSkillItem> & { id: string }): NativeSkillItem {
  return {
    name: partial.id,
    display_name: partial.id,
    description: '',
    short_description: '',
    version: '1.0.0',
    tags: [],
    imported_from: null,
    store_path: `~/.vibebara/skills/${partial.id}`,
    scope: 'personal',
    team_id: null,
    owner_id: 'dev-user',
    source_skill_id: null,
    content_hash: 'devmockhash',
    deployed_cursor: false,
    deployed_codex: false,
    deployed_windsurf: false,
    deployed_claude: false,
    deployed_kiro: false,
    deployed_trae: false,
    deployed_qoder: false,
    deployed_workbuddy: false,
    created_at: NOW,
    updated_at: NOW,
    ...partial,
  }
}

const PERSONAL_SKILLS: NativeSkillItem[] = [
  makeItem({
    id: 'build-website-ui',
    display_name: 'Build Website UI',
    description: '根据需求快速生成响应式网站前端 UI，覆盖落地页、仪表盘、组件样式与交互态。',
    short_description: '生成响应式网站前端 UI',
    version: '1.0.0',
    tags: ['frontend', 'ui', 'web'],
    imported_from: 'codex',
    deployed_cursor: true,
    deployed_codex: true,
  }),
  makeItem({
    id: 'image-gen',
    display_name: 'Image Gen',
    description: '调用图像生成系统技能，根据文本描述产出图标、插画与 UI 素材。',
    short_description: '文本生成图像素材',
    version: '2.1.0',
    tags: ['image', 'asset'],
    imported_from: 'claude',
    deployed_claude: true,
  }),
  makeItem({
    id: 'llm-test-helper',
    display_name: 'LLM Test Helper',
    description: '用于验证 LLM 连通性与基础能力的测试技能，包含若干基准提示词与断言。',
    short_description: 'LLM 连通性测试',
    version: '0.3.0',
    tags: ['test', 'llm'],
    deployed_cursor: true,
    deployed_qoder: true,
  }),
]

function makeTeamItem(
  partial: Partial<NativeSkillItem> & { id: string; team_id: string },
): NativeSkillItem {
  return makeItem({ scope: 'team', owner_id: null, ...partial })
}

const TEAM_SKILLS: NativeSkillItem[] = [
  // —— 团队：前端体验小队（dev-team）——
  makeTeamItem({
    id: 'team-code-reviewer',
    team_id: 'dev-team',
    display_name: 'Code Reviewer',
    description: '团队共享的代码评审技能，按团队规范输出结构化评审意见，覆盖命名、边界条件与安全检查。',
    short_description: '团队代码评审',
    version: '1.4.2',
    tags: ['review', 'team', 'quality'],
    deployed_cursor: true,
    deployed_codex: true,
  }),
  makeTeamItem({
    id: 'team-design-tokens',
    team_id: 'dev-team',
    display_name: 'Design Tokens',
    description: '统一团队设计令牌（颜色、间距、字体、圆角），并生成多端可消费的 CSS / TS 变量。',
    short_description: '设计令牌生成',
    version: '0.9.1',
    tags: ['design', 'css', 'tokens'],
    imported_from: 'cursor',
    deployed_cursor: true,
    deployed_windsurf: true,
  }),
  makeTeamItem({
    id: 'team-pr-summarizer',
    team_id: 'dev-team',
    display_name: 'PR Summarizer',
    description: '读取 diff 自动生成 PR 摘要与测试清单。',
    short_description: 'PR 摘要生成',
    version: '2.0.0',
    tags: ['git', 'automation'],
    imported_from: 'claude',
    deployed_claude: true,
  }),
  makeTeamItem({
    id: 'team-release-notes',
    team_id: 'dev-team',
    display_name: 'Release Notes',
    description: '从提交历史与合并的 PR 中归纳生成面向用户的发布说明，支持中英双语输出与分组。',
    short_description: '发布说明生成',
    version: '1.1.0',
    tags: ['release', 'docs', 'team'],
    deployed_codex: true,
    deployed_qoder: true,
  }),
  // —— 团队：设计系统公会（design-guild）——
  makeTeamItem({
    id: 'team-icon-forge',
    team_id: 'design-guild',
    display_name: 'Icon Forge',
    description: '按品牌风格批量生成线性 / 面性图标，并导出多尺寸 SVG 与雪碧图。',
    short_description: '图标批量生成',
    version: '3.2.0',
    tags: ['icon', 'svg', 'design'],
    imported_from: 'claude',
    deployed_claude: true,
    deployed_cursor: true,
  }),
  makeTeamItem({
    id: 'team-a11y-audit',
    team_id: 'design-guild',
    display_name: 'A11y Audit',
    description: '对页面做可访问性体检，输出对比度、语义标签与键盘可达性问题清单。',
    short_description: '可访问性体检',
    version: '0.5.3',
    tags: ['a11y', 'audit'],
    deployed_windsurf: true,
  }),
  // —— 团队：AI 实验室（ai-lab）——
  makeTeamItem({
    id: 'team-prompt-lab',
    team_id: 'ai-lab',
    display_name: 'Prompt Lab',
    description: '管理与评测提示词模板：维护版本、跑基准用例并对比多模型输出质量。',
    short_description: '提示词评测台',
    version: '1.0.0',
    tags: ['prompt', 'eval', 'llm'],
    deployed_cursor: true,
    deployed_codex: true,
    deployed_claude: true,
  }),
]

const ALL = [...PERSONAL_SKILLS, ...TEAM_SKILLS]

export function devMockSkillList(
  scope: 'personal' | 'team' = 'personal',
): NativeSkillListResponse {
  return {
    success: true,
    skills: scope === 'team' ? TEAM_SKILLS : PERSONAL_SKILLS,
  }
}

const VIBEH_BY_ID: Record<string, string> = {
  'build-website-ui': `# Build Website UI

## Overview
根据用户需求生成现代、响应式的网站前端界面，覆盖静态站点、落地页、产品页、仪表盘与 Web 应用。

## When to use
- 需要设计、构建、改造或实现网站 / 前端用户界面时
- 涉及 HTML/CSS/JS、React、Vue、Svelte、Next.js、Vite、Tailwind 等

## Workflow
1. 明确目标受众与页面信息架构
2. 选择技术栈与设计语言（配色、字体、间距体系）
3. 实现组件并补齐响应式断点与交互态
4. 在浏览器中验证视觉与可访问性
`,
  'image-gen': `# Image Gen

## Overview
将文本描述转为图标、插画与 UI 素材，支持品牌风格约束与多尺寸导出。
`,
  'llm-test-helper': `# LLM Test Helper

## Overview
用于验证 LLM 连通性与基础能力的测试技能，包含基准提示词与断言。
`,
  'team-code-reviewer': `# Code Reviewer

## Overview
团队共享的代码评审技能，按团队规范输出结构化评审意见。
`,
}

export function devMockSkillDetail(id: string): NativeSkillDetail {
  const db = ALL.find((s) => s.id === id) ?? makeItem({ id })
  return {
    success: true,
    id,
    store_path: db.store_path,
    db,
    vibeh_content: VIBEH_BY_ID[id] ?? `# ${db.display_name}\n\n## Overview\n${db.description}\n`,
    config: {
      name: db.id,
      description: db.description,
      policy: { auto_invoke: true },
      dependencies: {
        skills: id === 'build-website-ui' ? ['$imagegen'] : [],
      },
      resources: {
        scripts:
          id === 'build-website-ui'
            ? [{ path: 'scripts/scaffold.ts', description: '生成项目骨架' }]
            : [],
        references:
          id === 'build-website-ui'
            ? [{ path: 'references/design-tokens.md', description: '设计令牌规范' }]
            : [],
        assets: [],
      },
      metadata: {
        version: db.version,
        author: db.scope === 'team' ? db.team_id ?? 'dev-team' : 'dev',
        license: 'MIT',
        tags: db.tags,
      },
      _import_meta: {
        source: db.imported_from ?? 'manual',
        incomplete_fields: [],
      },
    },
  }
}

/* ===========================================================================
 * 团队 / 成员 / 项目 假数据（开发者模式 UI 调试用）
 * 约束同上：仅在 DEV_SKIP_AUTH 为真时由对应 api 守卫调用，生产构建恒不触达。
 * 团队 id 与上面 TEAM_SKILLS 的 team_id 对应，进入团队工作台后才能看到对应 Skill。
 * ======================================================================== */

function makeTeam(partial: Partial<TeamInfo> & { id: string; name: string }): TeamInfo {
  return {
    description: '',
    owner_id: 'dev-user',
    invite_code: partial.id.toUpperCase().slice(0, 6),
    max_members: 20,
    member_count: 1,
    auto_skill_hot_update: true,
    created_at: NOW,
    updated_at: NOW,
    ...partial,
  }
}

const DEV_TEAMS: TeamInfo[] = [
  makeTeam({
    id: 'dev-team',
    name: '前端体验小队',
    description: '负责产品 Web 端的界面体验、组件库与设计系统落地。',
    invite_code: 'FEX001',
    member_count: 5,
    max_members: 12,
  }),
  makeTeam({
    id: 'design-guild',
    name: '设计系统公会',
    description: '跨团队维护图标、配色与可访问性规范，沉淀共享 Skill。',
    invite_code: 'DSG777',
    member_count: 8,
    auto_skill_hot_update: false,
  }),
  makeTeam({
    id: 'ai-lab',
    name: 'AI 实验室',
    description: '探索提示词工程与多模型评测的实验性小组。',
    invite_code: 'AILAB3',
    member_count: 3,
  }),
]

function makeMember(
  partial: Partial<TeamMemberInfo> & { user_id: string; role: string },
): TeamMemberInfo {
  return {
    username: partial.user_id,
    display_name: partial.user_id,
    joined_at: NOW,
    ...partial,
  }
}

const DEV_MEMBERS: Record<string, TeamMemberInfo[]> = {
  'dev-team': [
    makeMember({ user_id: 'dev-user', username: 'dev', display_name: '我（开发者）', role: 'owner' }),
    makeMember({ user_id: 'lin', username: 'lin', display_name: '林晚', role: 'admin' }),
    makeMember({ user_id: 'zhao', username: 'zhao', display_name: '赵宇', role: 'member' }),
    makeMember({ user_id: 'qian', username: 'qian', display_name: '钱多多', role: 'member' }),
    makeMember({ user_id: 'sun', username: 'sun', display_name: '孙小白', role: 'member' }),
  ],
  'design-guild': [
    makeMember({ user_id: 'dev-user', username: 'dev', display_name: '我（开发者）', role: 'admin' }),
    makeMember({ user_id: 'wu', username: 'wu', display_name: '吴design', role: 'owner' }),
    makeMember({ user_id: 'zheng', username: 'zheng', display_name: '郑彩虹', role: 'member' }),
  ],
  'ai-lab': [
    makeMember({ user_id: 'dev-user', username: 'dev', display_name: '我（开发者）', role: 'member' }),
    makeMember({ user_id: 'feng', username: 'feng', display_name: '冯模型', role: 'owner' }),
  ],
}

function makeProject(
  partial: Partial<ProjectInfo> & { id: string; team_id: string; name: string },
): ProjectInfo {
  return {
    description: '',
    created_by: 'dev-user',
    skill_count: 0,
    pending_commit_count: 0,
    pending_update_count: 0,
    last_commit_at: null,
    created_at: NOW,
    updated_at: NOW,
    ...partial,
  }
}

const DEV_PROJECTS: Record<string, ProjectInfo[]> = {
  'dev-team': [
    makeProject({
      id: 'proj-web-revamp',
      team_id: 'dev-team',
      name: '官网改版',
      description: '落地页与定价页重做，统一组件与动效。',
      skill_count: 3,
      pending_commit_count: 2,
      pending_update_count: 1,
      last_commit_at: '2026-06-10T18:24:00',
    }),
    makeProject({
      id: 'proj-dashboard',
      team_id: 'dev-team',
      name: '控制台 2.0',
      description: '数据看板信息架构升级。',
      skill_count: 2,
      pending_update_count: 1,
      last_commit_at: '2026-06-08T10:12:00',
    }),
  ],
  'design-guild': [
    makeProject({
      id: 'proj-icon-set',
      team_id: 'design-guild',
      name: '图标库 v3',
      description: '新一批业务图标与暗色适配。',
      skill_count: 2,
    }),
  ],
  'ai-lab': [],
}

export function devMockTeamList(): TeamListResponse {
  return { success: true, teams: DEV_TEAMS }
}

export function devMockTeam(teamId: string): TeamResponse {
  const team = DEV_TEAMS.find((t) => t.id === teamId)
  return team
    ? { success: true, team }
    : { success: false, error: 'team not found (dev mock)' }
}

export function devMockUpdateTeam(
  teamId: string,
  name?: string | null,
  description?: string | null,
): TeamResponse {
  const team = DEV_TEAMS.find((t) => t.id === teamId)
  if (!team) return { success: false, error: 'team not found (dev mock)' }
  if (name != null) team.name = name
  if (description != null) team.description = description
  team.updated_at = new Date().toISOString()
  return { success: true, team }
}

export function devMockMembers(teamId: string): MemberListResponse {
  return { success: true, members: DEV_MEMBERS[teamId] ?? [] }
}

export function devMockProjectList(teamId: string): ProjectListResponse {
  return { success: true, projects: DEV_PROJECTS[teamId] ?? [] }
}

export function devMockUpdateProject(
  projectId: string,
  name?: string,
  description?: string,
): ProjectResponse {
  const project = findProjectAnyTeam(projectId)
  if (!project) {
    return { success: false, error: 'project not found (dev mock)' }
  }
  if (name !== undefined) project.name = name
  if (description !== undefined) project.description = description
  project.updated_at = new Date().toISOString()
  return { success: true, project: { ...project } }
}

/* ---------------------------------------------------------------------------
 * 项目详情假数据：让「团队项目 → 项目内」在开发者模式下也有 Skill，
 * 并覆盖部署的各种状态，使「部署 / 推送 / 更新本地 / 恢复跟踪 / 重新部署 /
 * 停止跟踪 / 移除」等按钮全部能渲染出来用于调 UI。
 * ------------------------------------------------------------------------ */

function findProjectAnyTeam(projectId: string): ProjectInfo | null {
  for (const list of Object.values(DEV_PROJECTS)) {
    const p = list.find((x) => x.id === projectId)
    if (p) return p
  }
  return null
}

function makeDeployment(
  projectId: string,
  skillId: string,
  partial: Partial<UserSkillDeploymentInfo>,
): UserSkillDeploymentInfo {
  return {
    id: `dep-${projectId}-${skillId}`,
    user_id: 'dev-user',
    project_id: projectId,
    team_skill_id: skillId,
    skill_name: skillId,
    tool_type: 'cursor',
    deploy_path: 'E:\\dev\\demo',
    install_path: `E:\\dev\\demo\\.cursor\\skills\\${skillId}`,
    repo_version: 1,
    repo_hash: 'repohash0001',
    installed_hash: 'repohash0001',
    status: 'synced',
    tracking_enabled: true,
    local_dirty: false,
    last_seen_at: NOW,
    created_at: NOW,
    updated_at: NOW,
    ...partial,
  }
}

function makeProjectSkill(
  partial: Partial<ProjectSkillInfo> & { skill_id: string },
): ProjectSkillInfo {
  return {
    display_name: partial.skill_id,
    description: '',
    version: 1,
    content_hash: 'devmockhash01',
    last_modified_by: '我（开发者）',
    updated_at: NOW,
    deployment: null,
    ...partial,
  }
}

function devMockProjectSkills(projectId: string): ProjectSkillInfo[] {
  return [
    // 1) 未部署 → 「部署」（点击弹出部署弹窗：工具选择 + 目录选择）
    makeProjectSkill({
      skill_id: 'build-website-ui',
      display_name: 'Build Website UI',
      description: '根据需求快速生成响应式网站前端 UI，覆盖落地页、仪表盘、组件样式与交互态。',
      version: 3,
      deployment: null,
    }),
    // 2) 已同步 + 跟踪中 → 「停止跟踪 / 移除」
    makeProjectSkill({
      skill_id: 'team-code-reviewer',
      display_name: 'Code Reviewer',
      description: '团队共享的代码评审技能，按团队规范输出结构化评审意见。',
      version: 2,
      deployment: makeDeployment(projectId, 'team-code-reviewer', {
        status: 'synced',
        tracking_enabled: true,
        local_dirty: false,
        tool_type: 'cursor',
      }),
    }),
    // 3) 有改动待推送 → 「推送」+ 右下角「有改动待推送」角标
    makeProjectSkill({
      skill_id: 'team-design-tokens',
      display_name: 'Design Tokens',
      description: '统一团队设计令牌（颜色、间距、字体、圆角），生成多端可消费的 CSS / TS 变量。',
      version: 5,
      deployment: makeDeployment(projectId, 'team-design-tokens', {
        status: 'changed',
        tracking_enabled: true,
        local_dirty: true,
        installed_hash: 'localdirty99',
        tool_type: 'codex',
      }),
    }),
    // 4) 可更新（团队仓库有新版本） → 「更新本地」
    makeProjectSkill({
      skill_id: 'team-pr-summarizer',
      display_name: 'PR Summarizer',
      description: '读取 diff 自动生成 PR 摘要与测试清单。',
      version: 4,
      deployment: makeDeployment(projectId, 'team-pr-summarizer', {
        status: 'outdated',
        tracking_enabled: true,
        local_dirty: false,
        repo_version: 4,
        repo_hash: 'newrepo0004',
        installed_hash: 'oldrepo0002',
        tool_type: 'windsurf',
      }),
    }),
    // 5) 已停止跟踪 → 「恢复跟踪」
    makeProjectSkill({
      skill_id: 'team-release-notes',
      display_name: 'Release Notes',
      description: '从提交历史与合并的 PR 中归纳生成面向用户的发布说明，支持中英双语输出与分组。',
      version: 1,
      deployment: makeDeployment(projectId, 'team-release-notes', {
        status: 'untracked',
        tracking_enabled: false,
        local_dirty: false,
        tool_type: 'claude',
      }),
    }),
    // 6) 路径缺失 → 「重新部署」
    makeProjectSkill({
      skill_id: 'team-icon-forge',
      display_name: 'Icon Forge',
      description: '按品牌风格批量生成线性 / 面性图标，并导出多尺寸 SVG 与雪碧图。',
      version: 2,
      deployment: makeDeployment(projectId, 'team-icon-forge', {
        status: 'missing',
        tracking_enabled: false,
        local_dirty: false,
        tool_type: 'cursor',
      }),
    }),
  ]
}

export function devMockProjectDetail(projectId: string): ProjectDetailResponse {
  const project =
    findProjectAnyTeam(projectId) ??
    makeProject({ id: projectId, team_id: 'dev-team', name: '示例项目' })
  const skills = devMockProjectSkills(projectId)
  return {
    success: true,
    project: { ...project, skill_count: skills.length },
    skills,
  }
}
