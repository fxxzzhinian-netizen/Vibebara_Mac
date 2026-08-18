<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppTopNav from '@/components/AppTopNav.vue'
import { toast } from '@/composables/useToast'
import { isDesktop } from '@/runtime/desktopBridge'

type ParagraphBlock = { type: 'paragraph'; text: string }
type ListBlock = { type: 'list' | 'steps'; items: string[] }
type CodeBlock = { type: 'code'; code: string }
type CalloutBlock = {
  type: 'callout'
  tone: 'info' | 'warning'
  title: string
  text: string
}
type DocBlock = ParagraphBlock | ListBlock | CodeBlock | CalloutBlock

interface DocSection {
  id: string
  title: string
  blocks: DocBlock[]
}

interface DocArticle {
  id: string
  group: string
  title: string
  description: string
  keywords: string[]
  sections: DocSection[]
}

const desktop = isDesktop()
const route = useRoute()
const router = useRouter()
const docsMainRef = ref<HTMLElement | null>(null)
const searchQuery = ref('')
const activeArticleId = ref('overview')
const activeSectionId = ref('')

const articles: DocArticle[] = [
  {
    id: 'overview',
    group: '快速开始',
    title: '认识 Vibebara',
    description: '了解 Vibebara 如何连接 Skill、团队项目和本机 Vibe Coding 工具。',
    keywords: ['简介', '产品', 'Cursor', 'Codex', 'Skill'],
    sections: [
      {
        id: 'what-is-vibebara',
        title: 'Vibebara 是什么',
        blocks: [
          {
            type: 'paragraph',
            text: 'Vibebara 是面向 Cursor、Codex 等 Vibe Coding 工具的 Skill 协作平台。你可以在个人仓库创建 Skill，在团队仓库共享 Skill，并把团队 Skill 部署到本机项目中持续同步。',
          },
          {
            type: 'list',
            items: [
              '统一管理个人与团队 Skill。',
              '支持项目关联、本机部署、推送、拉取和冲突合并。',
              '桌面安装包内置本地代理和 Vibebara CLI，普通用户无需安装 Node.js。',
              '当前支持 Cursor、Codex、Windsurf、Claude Code、Kiro、Trae、Qoder 和 WorkBuddy。',
            ],
          },
        ],
      },
      {
        id: 'recommended-flow',
        title: '推荐使用流程',
        blocks: [
          {
            type: 'steps',
            items: [
              '登录 Vibebara，完成首次工具选择。',
              '在个人仓库创建或导入 Skill。',
              '把 Skill 添加到团队仓库，再关联到团队项目。',
              '每位成员选择自己的项目目录完成部署。',
              '本地修改后推送；团队有更新时拉取；双方同时改动时先预览合并。',
            ],
          },
          {
            type: 'callout',
            tone: 'info',
            title: '关联不等于部署',
            text: '关联只会把 Skill 加入项目列表。只有执行“部署”后，Skill 才会写入本机项目目录并开始跟踪。',
          },
        ],
      },
    ],
  },
  {
    id: 'install',
    group: '快速开始',
    title: '安装与首次启动',
    description: '下载安装 Vibebara Desktop，并确认桌面端和 CLI 可用。',
    keywords: ['安装', '下载', 'Windows', 'CLI', 'PATH'],
    sections: [
      {
        id: 'install-desktop',
        title: '安装桌面客户端',
        blocks: [
          {
            type: 'steps',
            items: [
              '下载并运行 VBB-Setup 安装包。',
              '按安装向导完成安装，启动 Vibebara。',
              '如需使用 CLI，安装或升级后关闭并重新打开终端。',
            ],
          },
          {
            type: 'callout',
            tone: 'warning',
            title: 'Windows 安全提示',
            text: '当前安装包尚未完成代码签名，Windows SmartScreen 可能显示安全提醒。请确认安装包来自 Vibebara 官方发布地址。',
          },
        ],
      },
      {
        id: 'verify-cli',
        title: '验证 CLI',
        blocks: [
          { type: 'paragraph', text: '重新打开 PowerShell 后执行：' },
          { type: 'code', code: 'vibebara --version' },
          {
            type: 'paragraph',
            text: '如果提示找不到命令，请先重启终端，再检查 Vibebara 安装目录下的 resources\\cli。',
          },
        ],
      },
    ],
  },
  {
    id: 'account',
    group: '快速开始',
    title: '登录与首次引导',
    description: '完成账号登录、邀请码注册和首次工具选择。',
    keywords: ['登录', '注册', '邀请码', '滑块', '引导'],
    sections: [
      {
        id: 'sign-in',
        title: '登录或注册',
        blocks: [
          {
            type: 'steps',
            items: [
              '已有账号时输入用户名和密码，点击“登录”。',
              '按提示拖动滑块完成安全验证。',
              '新用户点击“没有账号？使用邀请码注册”，填写邀请码和账号信息。',
            ],
          },
          {
            type: 'callout',
            tone: 'info',
            title: '测试版注册',
            text: '当前注册需要有效邀请码，常见格式为 VH-XXXX-XXXX。邀请码无效或过期时请联系团队管理员。',
          },
          {
            type: 'callout',
            tone: 'warning',
            title: '单设备登录',
            text: '同一账号同一时间只能在一台设备登录。新设备登录会让旧设备自动退出，并使旧设备的 CLI/CI API Key 失效。',
          },
        ],
      },
      {
        id: 'onboarding',
        title: '完成首次引导',
        blocks: [
          {
            type: 'steps',
            items: [
              '选择“个人独立开发使用”或“团队协同开发”。',
              '等待 Vibebara 检测本机已安装的 Vibe Coding 工具。',
              '选择一个常用工具作为默认工具，点击“进入工作台”。',
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'personal-skills',
    group: 'Skill 管理',
    title: '创建与导入 Skill',
    description: '从空白、链接、本地文件夹或 IDE 创建个人 Skill。',
    keywords: ['新增', '导入', 'SKILL.md', '个人仓库', '编辑'],
    sections: [
      {
        id: 'create-skill',
        title: '新增 Skill',
        blocks: [
          {
            type: 'paragraph',
            text: '进入“个人空间 → SKILL 仓库”，点击“新增 Skill”。',
          },
          {
            type: 'list',
            items: ['手动新建', '从链接导入', '从本地文件夹导入', '从本机 IDE 工具导入'],
          },
          {
            type: 'callout',
            tone: 'info',
            title: '命名建议',
            text: 'Skill 名称建议只使用小写字母、数字和连字符，例如 develop-sop。本地文件夹必须包含 SKILL.md。',
          },
        ],
      },
      {
        id: 'edit-skill',
        title: '编辑与保存',
        blocks: [
          {
            type: 'paragraph',
            text: '点击个人 Skill 卡片进入编辑器，可维护介绍、基本信息、Skill 指令、资源、元数据和平台结构。',
          },
          {
            type: 'steps',
            items: ['完成编辑。', '看到“未保存”标记时点击“保存”。', '需要分享时再发布到市场或导入团队。'],
          },
        ],
      },
    ],
  },
  {
    id: 'market',
    group: 'Skill 管理',
    title: '使用 Skill 市场',
    description: '获取市场 Skill，或发布自己的 Skill 供其他用户使用。',
    keywords: ['市场', '获取', '发布', '审核'],
    sections: [
      {
        id: 'acquire',
        title: '获取市场 Skill',
        blocks: [
          {
            type: 'steps',
            items: [
              '进入“SKILL 市场”，打开目标 Skill。',
              '点击“获取到个人仓库”。',
              '回到个人空间的“SKILL 仓库”继续编辑或部署。',
            ],
          },
          {
            type: 'callout',
            tone: 'info',
            title: '获取后的范围',
            text: '市场 Skill 只会复制到个人仓库，不会自动加入团队，也不会自动部署到本机。',
          },
        ],
      },
      {
        id: 'publish',
        title: '发布自己的 Skill',
        blocks: [
          {
            type: 'steps',
            items: [
              '在个人 Skill 编辑器中保存最新内容。',
              '点击“发布到 SKILL 市场”。',
              '在“我的 SKILL”中查看审核中、已通过或已拒绝状态。',
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'team-project',
    group: '团队协作',
    title: '团队与项目',
    description: '创建团队、添加团队 Skill，并在项目中完成关联。',
    keywords: ['团队', '项目', '关联', '邀请'],
    sections: [
      {
        id: 'join-team',
        title: '创建或加入团队',
        blocks: [
          {
            type: 'paragraph',
            text: '点击右上角头像，可以创建团队或输入邀请码加入团队。随后在“空间选择”中切换到目标团队。',
          },
        ],
      },
      {
        id: 'add-team-skill',
        title: '准备团队 Skill',
        blocks: [
          {
            type: 'paragraph',
            text: '进入“团队 SKILL”，可以从个人仓库、本地文件夹或链接导入团队共享 Skill。',
          },
        ],
      },
      {
        id: 'link-project',
        title: '创建项目并关联 Skill',
        blocks: [
          {
            type: 'steps',
            items: [
              '进入“团队项目”，点击“新建项目”。',
              '打开项目详情，点击“关联 Skill”。',
              '从团队仓库选择 Skill 并点击“添加”。',
              '在项目 Skill 列表中继续执行本机部署。',
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'deploy',
    group: '团队协作',
    title: '部署到本机',
    description: '选择工具和项目目录，把团队 Skill 写入本机并开始跟踪。',
    keywords: ['部署', '项目目录', '全局', '覆盖', '路径'],
    sections: [
      {
        id: 'deploy-steps',
        title: '部署步骤',
        blocks: [
          {
            type: 'steps',
            items: [
              '在项目 Skill 列表中找到“未部署”的 Skill，点击“部署”。',
              '选择 Cursor、Codex 等目标工具。',
              '选择本机项目文件夹。',
              '按需选择“同时部署到全局”和“覆盖已存在的同名 Skill”。',
              '点击“部署”，完成后可选择打开对应工具。',
            ],
          },
        ],
      },
      {
        id: 'deploy-path',
        title: '部署目录',
        blocks: [
          {
            type: 'paragraph',
            text: '项目级 Skill 会写入项目中的工具目录。例如 Cursor Skill 通常位于：',
          },
          { type: 'code', code: 'E:\\my-project\\.cursor\\skills\\develop-sop\\' },
          {
            type: 'callout',
            tone: 'warning',
            title: '全局部署不会跟踪',
            text: '“同时部署到全局”是一次性复制。项目协作只跟踪项目目录中的部署实例。',
          },
        ],
      },
    ],
  },
  {
    id: 'sync',
    group: '团队协作',
    title: '推送、拉取与合并',
    description: '理解同步状态，并安全处理本地改动、团队更新和冲突。',
    keywords: ['推送', '拉取', '更新', '冲突', '合并', '同步'],
    sections: [
      {
        id: 'status',
        title: '状态说明',
        blocks: [
          {
            type: 'list',
            items: [
              '已同步：本地内容与团队仓库一致。',
              '待推送：本地有尚未提交的改动。',
              '待更新：团队仓库已有新版本。',
              '冲突：本地和团队仓库都发生了改动。',
              '路径缺失：部署目录已移动或删除。',
              '停止跟踪：该部署实例暂不参与同步。',
            ],
          },
        ],
      },
      {
        id: 'push-pull',
        title: '推送与更新本地',
        blocks: [
          {
            type: 'steps',
            items: [
              '本地修改完成后，在“待推送”状态点击“推送”。',
              '看到“待更新”时，确认本地没有需要保留的未推送改动，再点击“更新本地”。',
              '拉取被阻止时，优先推送或合并，不要直接覆盖重要内容。',
            ],
          },
        ],
      },
      {
        id: 'merge',
        title: '处理冲突',
        blocks: [
          {
            type: 'steps',
            items: [
              '点击“AI 合并”生成合并预览。',
              '检查正文、配置和资源改动。',
              '遇到人工冲突时先确认处理方式。',
              '确认预览正确后提交合并。',
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'cli-start',
    group: 'CLI',
    title: 'CLI 授权与状态',
    description: '从桌面端生成 API Key，并在终端验证部署状态。',
    keywords: ['CLI', 'API Key', 'whoami', 'status', '授权'],
    sections: [
      {
        id: 'authorize-cli',
        title: '为 CLI 授权',
        blocks: [
          {
            type: 'steps',
            items: [
              '登录 Vibebara Desktop。',
              '点击右上角头像，选择“生成 CLI API Key”。',
              '已有 Key 时可以选择“轮换 CLI API Key”。',
              '重新打开终端，执行 vibebara whoami。',
            ],
          },
          { type: 'code', code: 'vibebara whoami' },
          {
            type: 'callout',
            tone: 'warning',
            title: '保护 API Key',
            text: 'CLI 配置保存在 %USERPROFILE%\\.vibebara\\config.json。Key 绑定当前桌面设备；在另一台设备登录后旧 Key 会失效。不要分享该文件，也不要提交到 Git。',
          },
        ],
      },
      {
        id: 'check-status',
        title: '查看状态',
        blocks: [
          { type: 'code', code: 'vibebara status\nvibebara status --json' },
          {
            type: 'paragraph',
            text: 'CLI 只能操作已经通过当前电脑上的 Vibebara Desktop 部署过的 Skill。',
          },
        ],
      },
    ],
  },
  {
    id: 'cli-sync',
    group: 'CLI',
    title: 'CLI 同步命令',
    description: '使用 push、pull 和 merge 完成无界面的 Skill 协作。',
    keywords: ['push', 'pull', 'merge', 'preview', 'overwrite'],
    sections: [
      {
        id: 'cli-push',
        title: '推送本地改动',
        blocks: [
          { type: 'code', code: 'vibebara push <skill-name>' },
          {
            type: 'paragraph',
            text: '需要同时创建版本时，可增加 --create-version、--version-number 和 --version-label。',
          },
        ],
      },
      {
        id: 'cli-pull',
        title: '拉取团队更新',
        blocks: [
          {
            type: 'code',
            code: 'vibebara pull <skill-name>\nvibebara pull <skill-name> --overwrite',
          },
          {
            type: 'callout',
            tone: 'warning',
            title: '谨慎使用 --overwrite',
            text: '覆盖拉取会放弃本地未推送改动。确认这些改动不再需要后再使用。',
          },
        ],
      },
      {
        id: 'cli-merge',
        title: '预览并提交合并',
        blocks: [
          {
            type: 'code',
            code: 'vibebara merge <skill-name> --preview --json\nvibebara --yes merge <skill-name> --json',
          },
        ],
      },
    ],
  },
  {
    id: 'troubleshooting',
    group: '问题排查',
    title: '常见问题',
    description: '排查 CLI、部署路径、同步连接和登录问题。',
    keywords: ['错误', 'PATH', '跨机', '路径缺失', '同步断开'],
    sections: [
      {
        id: 'cli-not-found',
        title: '找不到 vibebara 命令',
        blocks: [
          {
            type: 'steps',
            items: [
              '关闭并重新打开终端。',
              '执行 Get-Command vibebara。',
              '确认安装目录的 resources\\cli 中存在 vibebara.exe。',
            ],
          },
          {
            type: 'code',
            code: '& "$env:LOCALAPPDATA\\Programs\\Vibebara\\resources\\cli\\vibebara.exe" --version',
          },
        ],
      },
      {
        id: 'same-machine',
        title: 'CLI 提示暂不支持跨机',
        blocks: [
          {
            type: 'paragraph',
            text: '部署记录包含原电脑上的绝对路径。换电脑、移动项目或重命名 Skill 目录后，请在当前电脑使用桌面客户端重新部署。',
          },
        ],
      },
      {
        id: 'sync-disconnected',
        title: '页面显示同步断开',
        blocks: [
          {
            type: 'steps',
            items: [
              '检查网络连接并等待自动重连。',
              '刷新页面或重新启动客户端。',
              '持续断开时联系管理员检查云端 WebSocket 服务。',
            ],
          },
        ],
      },
    ],
  },
  {
    id: 'security',
    group: '问题排查',
    title: '数据与安全',
    description: '了解本地数据位置、代理边界和当前版本限制。',
    keywords: ['安全', '配置', 'Token', '本地代理', '限制'],
    sections: [
      {
        id: 'local-data',
        title: '本地数据位置',
        blocks: [
          {
            type: 'list',
            items: [
              '桌面配置与登录数据：%APPDATA%\\@vibebara\\desktop',
              'CLI 配置：%USERPROFILE%\\.vibebara\\config.json',
              '卸载桌面客户端不会自动删除这些用户数据。',
            ],
          },
        ],
      },
      {
        id: 'agent-security',
        title: '本地代理安全边界',
        blocks: [
          {
            type: 'list',
            items: [
              '本地代理只监听 127.0.0.1。',
              '非健康检查接口使用随机配对令牌。',
              '文件写入限制在用户选择的项目目录和受支持的 Skill 目录中。',
            ],
          },
        ],
      },
      {
        id: 'current-limits',
        title: '当前限制',
        blocks: [
          {
            type: 'list',
            items: [
              '桌面客户端当前以 Windows 为主要支持平台。',
              'CLI 只支持同机部署，不支持跨机自动迁移路径。',
              '全局部署副本不参与项目同步跟踪。',
              '当前测试云端可能仍使用 HTTP/WS，不应传输高敏感内容。',
            ],
          },
        ],
      },
    ],
  },
]

const groupOrder = ['快速开始', 'Skill 管理', '团队协作', 'CLI', '问题排查']

const activeArticle = computed(
  () => articles.find((article) => article.id === activeArticleId.value) ?? articles[0]!,
)

const activeSectionIndex = computed(() =>
  activeArticle.value.sections.findIndex((section) => section.id === activeSectionId.value),
)

const filteredGroups = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  return groupOrder
    .map((group) => ({
      group,
      articles: articles.filter((article) => {
        if (article.group !== group) return false
        if (!query) return true
        return [article.title, article.description, ...article.keywords]
          .join(' ')
          .toLowerCase()
          .includes(query)
      }),
    }))
    .filter((item) => item.articles.length)
})

function selectArticle(id: string) {
  searchQuery.value = ''
  if (id === activeArticleId.value) {
    docsMainRef.value?.scrollTo({ top: 0, behavior: 'smooth' })
    return
  }
  void router.push({ path: '/help', query: { article: id } })
}

function selectArticleFromEvent(event: Event) {
  const target = event.target as HTMLSelectElement
  selectArticle(target.value)
}

function scrollToSection(id: string) {
  activeSectionId.value = id
  const section = document.getElementById(`help-${id}`)
  section?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function updateActiveSection() {
  const container = docsMainRef.value
  if (!container) return
  const containerScrollable = container.scrollHeight > container.clientHeight + 1
  const viewportTop = containerScrollable ? container.getBoundingClientRect().top : 0
  const viewportHeight = containerScrollable ? container.clientHeight : window.innerHeight
  const marker = viewportTop + Math.min(180, viewportHeight * 0.24)
  let current = activeArticle.value.sections[0]?.id ?? ''

  for (const section of activeArticle.value.sections) {
    const element = document.getElementById(`help-${section.id}`)
    if (element && element.getBoundingClientRect().top <= marker) {
      current = section.id
    }
  }

  const pageScrollable = document.documentElement.scrollHeight > window.innerHeight + 1
  const atBottom = containerScrollable
    ? container.scrollTop + container.clientHeight >= container.scrollHeight - 4
    : pageScrollable &&
      window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 4
  if (atBottom) {
    current = activeArticle.value.sections.at(-1)?.id ?? current
  }

  activeSectionId.value = current
}

async function copyCode(code: string) {
  try {
    await navigator.clipboard.writeText(code)
    toast.success('命令已复制')
  } catch {
    toast.error('复制失败，请手动复制')
  }
}

watch(
  () => route.query.article,
  (articleId) => {
    const nextId =
      typeof articleId === 'string' && articles.some((article) => article.id === articleId)
        ? articleId
        : 'overview'
    activeArticleId.value = nextId
  },
  { immediate: true },
)

watch(activeArticleId, async () => {
  activeSectionId.value = activeArticle.value.sections[0]?.id ?? ''
  await nextTick()
  docsMainRef.value?.scrollTo({ top: 0 })
  updateActiveSection()
})

onMounted(() => {
  window.addEventListener('scroll', updateActiveSection, { passive: true })
  nextTick(updateActiveSection)
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', updateActiveSection)
})
</script>

<template>
  <div :class="['help-page', { 'is-desktop': desktop }]">
    <AppTopNav />

    <div class="docs-shell">
      <aside class="docs-sidebar" aria-label="使用帮助目录">
        <label class="docs-search">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m16.5 16.5 4 4" />
          </svg>
          <input
            v-model="searchQuery"
            type="search"
            placeholder="搜索文档"
            aria-label="搜索帮助文档"
          />
          <button
            v-if="searchQuery"
            type="button"
            aria-label="清除搜索"
            @click="searchQuery = ''"
          >
            ×
          </button>
        </label>

        <select
          class="mobile-article-select"
          :value="activeArticle.id"
          aria-label="选择帮助文档"
          @change="selectArticleFromEvent"
        >
          <optgroup v-for="item in filteredGroups" :key="item.group" :label="item.group">
            <option v-for="article in item.articles" :key="article.id" :value="article.id">
              {{ article.title }}
            </option>
          </optgroup>
        </select>

        <nav class="docs-menu">
          <template v-for="item in filteredGroups" :key="item.group">
            <p class="docs-menu-group">{{ item.group }}</p>
            <button
              v-for="article in item.articles"
              :key="article.id"
              type="button"
              :class="['docs-menu-item', { active: activeArticle.id === article.id }]"
              @click="selectArticle(article.id)"
            >
              {{ article.title }}
            </button>
          </template>
          <div v-if="!filteredGroups.length" class="docs-search-empty">
            没有找到相关文档
          </div>
        </nav>
      </aside>

      <main ref="docsMainRef" class="docs-main" @scroll.passive="updateActiveSection">
        <article class="docs-article">
          <div class="article-breadcrumb">
            <span>使用帮助</span>
            <svg viewBox="0 0 16 16" aria-hidden="true"><path d="m6 3.5 4 4-4 4" /></svg>
            <span>{{ activeArticle.group }}</span>
          </div>

          <header class="article-header">
            <h1>{{ activeArticle.title }}</h1>
            <p>{{ activeArticle.description }}</p>
          </header>

          <section
            v-for="section in activeArticle.sections"
            :id="`help-${section.id}`"
            :key="section.id"
            class="article-section"
          >
            <h2>{{ section.title }}</h2>
            <template v-for="(block, blockIndex) in section.blocks" :key="blockIndex">
              <p v-if="block.type === 'paragraph'" class="doc-paragraph">{{ block.text }}</p>

              <ul v-else-if="block.type === 'list'" class="doc-list">
                <li v-for="item in block.items" :key="item">{{ item }}</li>
              </ul>

              <ol v-else-if="block.type === 'steps'" class="doc-steps">
                <li v-for="item in block.items" :key="item">
                  <span>{{ item }}</span>
                </li>
              </ol>

              <div v-else-if="block.type === 'code'" class="doc-code">
                <div class="doc-code-toolbar">
                  <span>PowerShell</span>
                  <button type="button" @click="copyCode(block.code)">
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <rect x="8" y="8" width="11" height="11" rx="2" />
                      <path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" />
                    </svg>
                    复制
                  </button>
                </div>
                <pre><code>{{ block.code }}</code></pre>
              </div>

              <aside v-else-if="block.type === 'callout'" :class="['doc-callout', block.tone]">
                <svg v-if="block.tone === 'warning'" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M10.3 4.2 2.5 18a2 2 0 0 0 1.75 3h15.5a2 2 0 0 0 1.75-3L13.7 4.2a2 2 0 0 0-3.4 0Z" />
                  <path d="M12 9v4M12 17h.01" />
                </svg>
                <svg v-else viewBox="0 0 24 24" aria-hidden="true">
                  <circle cx="12" cy="12" r="9" />
                  <path d="M12 11v6M12 7h.01" />
                </svg>
                <div>
                  <strong>{{ block.title }}</strong>
                  <p>{{ block.text }}</p>
                </div>
              </aside>
            </template>
          </section>

        </article>
      </main>

      <aside class="docs-outline" aria-label="本文目录">
        <p>本页目录</p>
        <div class="outline-steps">
          <button
            v-for="(section, sectionIndex) in activeArticle.sections"
            :key="section.id"
            type="button"
            :class="{
              active: activeSectionId === section.id,
              completed: sectionIndex < activeSectionIndex,
            }"
            @click="scrollToSection(section.id)"
          >
            {{ section.title }}
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.help-page {
  min-height: 100vh;
  background: #ffffff;
  color: #1f2328;
  font-family: Inter, 'PingFang SC', 'Microsoft YaHei', -apple-system, BlinkMacSystemFont,
    'Segoe UI', sans-serif;
}

.docs-shell {
  height: calc(100vh - 84px);
  display: grid;
  grid-template-columns: 258px minmax(0, 1fr) 220px;
  overflow: hidden;
}

.help-page.is-desktop .docs-shell {
  height: calc(100vh - 124px);
}

.docs-sidebar {
  min-width: 0;
  overflow-y: auto;
  padding: 22px 16px 32px;
  background: #fbfbfc;
}

.docs-search {
  height: 38px;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 4px 22px;
  padding: 0 10px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f0f1f3;
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}

.docs-search:focus-within {
  border-color: #aeb4bc;
  background: #ffffff;
  box-shadow: 0 0 0 3px rgba(31, 35, 40, 0.07);
}

.docs-search > svg {
  width: 17px;
  height: 17px;
  flex-shrink: 0;
  fill: none;
  stroke: #7b828c;
  stroke-width: 1.8;
  stroke-linecap: round;
}

.docs-search input {
  width: 100%;
  min-width: 0;
  border: none;
  outline: none;
  background: transparent;
  color: #25292e;
  font: inherit;
  font-size: 13px;
}

.docs-search input::-webkit-search-cancel-button {
  display: none;
}

.docs-search button {
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: none;
  border-radius: 4px;
  background: transparent;
  color: #8b929b;
  font: inherit;
  font-size: 17px;
  cursor: pointer;
}

.docs-search button:hover {
  background: #e7e9ec;
  color: #30343a;
}

.mobile-article-select {
  display: none;
}

.docs-menu-group {
  margin: 20px 10px 7px;
  color: #8b929b;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.docs-menu-group:first-child {
  margin-top: 0;
}

.docs-menu-item {
  width: 100%;
  min-height: 38px;
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border: none;
  border-radius: 7px;
  background: transparent;
  color: #59616b;
  font: inherit;
  font-size: 13px;
  font-weight: 450;
  line-height: 1.4;
  text-align: left;
  cursor: pointer;
  transition: background 0.12s ease, color 0.12s ease;
}

.docs-menu-item:hover {
  background: #eef0f2;
  color: #1f2328;
}

.docs-menu-item.active {
  background: #e7e9ec;
  color: #1f2328;
  font-weight: 600;
}

.docs-menu-item:focus-visible,
.docs-outline button:focus-visible {
  outline: 2px solid #7a828d;
  outline-offset: 2px;
}

.docs-search-empty {
  padding: 18px 10px;
  color: #9299a2;
  font-size: 13px;
  text-align: center;
}

.docs-main {
  min-width: 0;
  overflow-y: auto;
  background: #ffffff;
  scroll-behavior: smooth;
}

.docs-article {
  width: min(100%, 860px);
  margin: 0 auto;
  padding: 48px 58px 80px;
}

.article-breadcrumb {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-bottom: 22px;
  color: #8b929b;
  font-size: 12px;
}

.article-breadcrumb svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.5;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.article-header {
  padding-bottom: 34px;
  border-bottom: 1px solid #eef0f2;
}

.article-header h1 {
  margin: 0;
  color: #1f2328;
  font-size: 32px;
  font-weight: 700;
  line-height: 1.25;
}

.article-header p {
  max-width: 680px;
  margin: 12px 0 0;
  color: #69717c;
  font-size: 15px;
  line-height: 1.75;
}

.article-section {
  padding-top: 38px;
  scroll-margin-top: 24px;
}

.article-section h2 {
  margin: 0 0 18px;
  color: #24282d;
  font-size: 21px;
  font-weight: 650;
  line-height: 1.4;
}

.doc-paragraph {
  margin: 0 0 16px;
  color: #4e5661;
  font-size: 14px;
  line-height: 1.85;
}

.doc-list {
  margin: 0 0 18px;
  padding-left: 22px;
  color: #4e5661;
  font-size: 14px;
  line-height: 1.8;
}

.doc-list li {
  padding-left: 3px;
}

.doc-list li + li {
  margin-top: 6px;
}

.doc-list li::marker {
  color: #858c95;
}

.doc-steps {
  margin: 0 0 20px;
  padding: 0;
  list-style: none;
  counter-reset: doc-step;
}

.doc-steps li {
  position: relative;
  min-height: 34px;
  display: flex;
  gap: 12px;
  color: #4e5661;
  counter-increment: doc-step;
  font-size: 14px;
  line-height: 1.7;
}

.doc-steps li::before {
  content: counter(doc-step);
  width: 22px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 22px;
  margin-top: 1px;
  border-radius: 50%;
  background: #eff1f3;
  color: #505761;
  font-size: 11px;
  font-weight: 650;
}

.doc-steps li:not(:last-child)::after {
  content: '';
  position: absolute;
  top: 25px;
  bottom: 2px;
  left: 10.5px;
  width: 1px;
  background: #e3e6e9;
}

.doc-steps li + li {
  padding-top: 7px;
}

.doc-code {
  margin: 18px 0 22px;
  overflow: hidden;
  border: 1px solid #e4e7ea;
  border-radius: 8px;
  background: #f7f8f9;
}

.doc-code-toolbar {
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 10px 0 14px;
  border-bottom: 1px solid #e4e7ea;
  background: #f1f3f4;
}

.doc-code-toolbar > span {
  color: #7b828c;
  font-size: 11px;
  font-weight: 600;
}

.doc-code-toolbar button {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 4px 7px;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: #646b74;
  font: inherit;
  font-size: 11px;
  cursor: pointer;
}

.doc-code-toolbar button:hover {
  background: #e3e6e9;
  color: #282d33;
}

.doc-code-toolbar svg {
  width: 14px;
  height: 14px;
  fill: none;
  stroke: currentColor;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.doc-code pre {
  margin: 0;
  overflow-x: auto;
  padding: 16px 18px 18px;
}

.doc-code code {
  color: #30363d;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: 12.5px;
  line-height: 1.7;
  white-space: pre;
}

.doc-callout {
  display: flex;
  gap: 11px;
  margin: 18px 0 22px;
  padding: 14px 16px;
  border: 1px solid #dfe6ee;
  border-radius: 8px;
  background: #f5f8fb;
}

.doc-callout.warning {
  border-color: #eadfca;
  background: #fbf8f1;
}

.doc-callout > svg {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  margin-top: 1px;
  fill: none;
  stroke: #4e6b87;
  stroke-width: 1.7;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.doc-callout.warning > svg {
  stroke: #9a6b20;
}

.doc-callout strong {
  display: block;
  margin-bottom: 4px;
  color: #34495d;
  font-size: 13px;
  font-weight: 650;
}

.doc-callout.warning strong {
  color: #765320;
}

.doc-callout p {
  margin: 0;
  color: #617080;
  font-size: 13px;
  line-height: 1.7;
}

.doc-callout.warning p {
  color: #796746;
}

.docs-outline {
  overflow-y: auto;
  padding: 48px 20px 32px;
  border-left: 1px solid #eef0f2;
  background: #ffffff;
}

.docs-outline > p {
  margin: 0 0 12px;
  color: #8b929b;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
}

.outline-steps {
  position: relative;
}

.outline-steps::before {
  content: '';
  position: absolute;
  top: 19px;
  bottom: 19px;
  left: 10px;
  width: 1px;
  background: #dfe3e7;
}

.docs-outline button {
  position: relative;
  z-index: 1;
  width: 100%;
  height: 38px;
  display: block;
  padding: 8px 0 8px 30px;
  border: none;
  background: transparent;
  color: #858c95;
  font: inherit;
  font-size: 12px;
  line-height: 1.45;
  text-align: left;
  cursor: pointer;
  transition: color 0.15s ease;
}

.docs-outline button::before {
  content: '';
  position: absolute;
  top: 50%;
  left: 4px;
  z-index: 2;
  width: 9px;
  height: 9px;
  border: 2px solid #cbd0d6;
  border-radius: 50%;
  background: #ffffff;
  transform: translateY(-50%);
  transition: border-color 0.15s ease, background 0.15s ease, box-shadow 0.15s ease;
}

.docs-outline button:hover {
  color: #30363d;
}

.docs-outline button:hover::before {
  border-color: #7b838d;
}

.docs-outline button.completed {
  color: #66717d;
  font-weight: 500;
}

.docs-outline button.completed::before {
  content: '✓';
  left: 2px;
  width: 13px;
  height: 13px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-color: #b6c0ca;
  background: #eef2f5;
  color: #667380;
  font-size: 8px;
  font-weight: 700;
  line-height: 1;
}

.docs-outline button.active::before {
  border-color: #30363d;
  background: #30363d;
}

.docs-outline button.active {
  color: #30363d;
  font-size: 14px;
  font-weight: 650;
}

.docs-outline button.active::before {
  left: 1px;
  width: 13px;
  height: 13px;
  border: 3px solid #ffffff;
  box-shadow: 0 0 0 3px #dfe3e7;
}

@media (max-width: 1120px) {
  .docs-shell {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  .docs-outline {
    display: none;
  }
}

@media (max-width: 760px) {
  .help-page :deep(.nav-links) {
    display: none;
  }

  .help-page :deep(.nav-inner) {
    grid-template-columns: auto minmax(0, 1fr) auto;
  }

  .help-page :deep(.nav-right) {
    grid-column: 3;
  }

  .docs-shell,
  .help-page.is-desktop .docs-shell {
    min-height: calc(100vh - 84px);
    height: auto;
    display: block;
    overflow: visible;
  }

  .help-page.is-desktop .docs-shell {
    min-height: calc(100vh - 124px);
  }

  .docs-sidebar {
    position: relative;
    width: 100%;
    overflow: visible;
    padding: 16px 18px;
    border-right: none;
    border-bottom: 1px solid #e8ebef;
  }

  .docs-search {
    margin: 0 0 12px;
  }

  .mobile-article-select {
    width: 100%;
    height: 40px;
    display: block;
    padding: 0 36px 0 11px;
    border: 1px solid #dfe3e7;
    border-radius: 8px;
    outline: none;
    background: #ffffff;
    color: #30363d;
    font: inherit;
    font-size: 13px;
  }

  .mobile-article-select:focus {
    border-color: #8b929b;
    box-shadow: 0 0 0 3px rgba(31, 35, 40, 0.07);
  }

  .docs-menu {
    display: none;
  }

  .docs-main {
    overflow: visible;
  }

  .docs-article {
    padding: 30px 20px 60px;
  }

  .article-header {
    padding-bottom: 26px;
  }

  .article-header h1 {
    font-size: 26px;
  }

  .article-header p {
    font-size: 14px;
  }

  .article-section {
    padding-top: 30px;
  }

  .article-section h2 {
    font-size: 19px;
  }

}
</style>
