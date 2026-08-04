<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useSkillStore } from '@/stores/skillStore'
import FolderPicker from '@/components/FolderPicker.vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect from '@/components/BaseSelect.vue'
import cursorIcon from '@/img/icon/cursor.svg'
import codexIcon from '@/img/icon/codex.svg'
import windsurfIcon from '@/img/icon/windsurf.svg'
import claudeIcon from '@/img/icon/claudecode.svg'
import kiroIcon from '@/img/icon/kiro.svg'
import traeIcon from '@/img/icon/trae.svg'
import qoderIcon from '@/img/icon/qoder.svg'
import workbuddyIcon from '@/img/icon/workbuddy.svg'

// 平台结构内容面板：可内嵌于 SkillForge 标签页，也可被 PlatformStructure 路由页包裹复用。
// 默认直接读写 skillStore.currentConfig（updateLocalConfig 会置 dirty，由外层工具栏统一保存）；
// 传入 configSource + readonly 时改为只读渲染该 config（如市场快照），不写 store。
const props = defineProps<{
  configSource?: Record<string, any> | null
  readonly?: boolean
}>()

const store = useSkillStore()

const platformIcons: Record<string, string> = {
  codex: codexIcon,
  cursor: cursorIcon,
  windsurf: windsurfIcon,
  claude: claudeIcon,
  kiro: kiroIcon,
  trae: traeIcon,
  qoder: qoderIcon,
  workbuddy: workbuddyIcon,
}

const activePlatform = ref<
  'overview' | 'codex' | 'cursor' | 'windsurf' | 'claude' | 'kiro' | 'trae' | 'qoder' | 'workbuddy'
>('overview')

const cfg = computed(
  () => (props.configSource ?? store.currentConfig) as Record<string, any> | null,
)

function setNestedField(parent: string, key: string, val: unknown) {
  if (props.readonly) return
  if (!cfg.value) return
  const current = (cfg.value[parent] as Record<string, unknown>) ?? {}
  store.updateLocalConfig({ [parent]: { ...current, [key]: val } })
}

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'textarea' | 'color' | 'json' | 'tags' | 'select' | 'boolean' | 'path'
  parent: string
  placeholder?: string
  options?: string[]
  help?: string
  platforms: ('cursor' | 'codex' | 'windsurf' | 'claude' | 'kiro' | 'trae' | 'qoder' | 'workbuddy')[]
}

const allFields: FieldDef[] = [
  // Codex UI fields
  { key: 'display_name', label: '显示名称', type: 'text', parent: 'ui', placeholder: '人类友好的标题', help: '在 Codex 界面上展示给用户看的标题，可以比 Skill 的 ID 更友好易读。', platforms: ['codex'] },
  { key: 'short_description', label: '简短描述', type: 'text', parent: 'ui', placeholder: '25-64 字符摘要', help: '一句话概括这个 Skill 的用途，会显示在 Codex 的列表或卡片上（建议 25–64 个字符）。', platforms: ['codex'] },
  { key: 'brand_color', label: '品牌颜色', type: 'color', parent: 'ui', placeholder: '#3B82F6', help: 'Skill 在 Codex 界面中的主题色，用十六进制色值填写，例如 #3B82F6。', platforms: ['codex'] },
  { key: 'default_prompt', label: '默认提示词', type: 'text', parent: 'ui', placeholder: 'Use $skill-name to ...', help: '用户选用该 Skill 时自动填入的示例指令，方便快速上手。', platforms: ['codex'] },
  { key: 'icon_small', label: '小图标路径', type: 'path', parent: 'ui', placeholder: './assets/icon-small.svg', help: '小尺寸图标的文件路径，用于列表等紧凑位置，例如 ./assets/icon-small.svg。可点击「浏览…」选择文件夹。', platforms: ['codex'] },
  { key: 'icon_large', label: '大图标路径', type: 'path', parent: 'ui', placeholder: './assets/icon-large.svg', help: '大尺寸图标的文件路径，用于详情等较大位置，例如 ./assets/icon-large.svg。可点击「浏览…」选择文件夹。', platforms: ['codex'] },
  // Cursor field
  { key: 'surfaces', label: '适用界面 (surfaces)', type: 'tags', parent: 'metadata', placeholder: 'ide, panel', help: '限定该 Skill 在 Cursor 的哪些界面出现（如 ide、panel），多个用逗号分隔；留空表示不限制。', platforms: ['cursor'] },
  // Claude Code 专有运行时字段（写入同一 SKILL.md frontmatter）
  { key: 'model', label: '模型 (model)', type: 'text', parent: 'claude', placeholder: 'haiku | sonnet | opus 或完整模型 ID', help: '指定运行该 Skill 时使用的模型，可填 haiku / sonnet / opus 或完整模型 ID；留空则用默认模型。', platforms: ['claude'] },
  { key: 'effort', label: '推理强度 (effort)', type: 'text', parent: 'claude', placeholder: 'low | medium | high | max', help: '控制模型思考的深度，可填 low / medium / high / max；越高越细致，但更慢、消耗更多。', platforms: ['claude'] },
  { key: 'context', label: '运行上下文 (context)', type: 'select', parent: 'claude', options: ['', 'inline', 'fork'], help: 'inline 表示在当前对话中直接运行；fork 表示新开一个独立子上下文运行（此时才会用到下面的“子代理类型”）。', platforms: ['claude'] },
  { key: 'agent', label: '子代理类型 (agent)', type: 'text', parent: 'claude', placeholder: '仅 context: fork 时生效，如 Explore / Plan', help: '仅当“运行上下文”为 fork 时生效，指定由哪种子代理来执行，例如 Explore / Plan。', platforms: ['claude'] },
  { key: 'allowed_tools', label: '允许工具 (allowed-tools)', type: 'tags', parent: 'claude', placeholder: 'Read, Grep, Glob', help: '白名单：只允许该 Skill 使用这里列出的工具（如 Read、Grep、Glob），多个用逗号分隔。', platforms: ['claude'] },
  { key: 'disallowed_tools', label: '禁用工具 (disallowed-tools)', type: 'tags', parent: 'claude', placeholder: 'AskUserQuestion', help: '黑名单：禁止该 Skill 使用这里列出的工具（如 AskUserQuestion），多个用逗号分隔。', platforms: ['claude'] },
  { key: 'argument_hint', label: '参数提示 (argument-hint)', type: 'text', parent: 'claude', placeholder: '<environment>', help: '提示用户该 Skill 需要输入什么参数，会作为输入占位显示，例如 <environment>。', platforms: ['claude'] },
  { key: 'when_to_use', label: '触发提示 (when_to_use)', type: 'textarea', parent: 'claude', placeholder: 'Use when user asks to deploy.', help: '用自然语言描述什么情况下应该使用这个 Skill，帮助模型判断是否自动调用。', platforms: ['claude'] },
  { key: 'user_invocable', label: '可手动调用 (user-invocable)', type: 'boolean', parent: 'claude', help: '是否允许用户手动调用该 Skill；设为 false 则只能由模型自动触发。', platforms: ['claude'] },
  { key: 'hooks', label: 'Hooks (高级, JSON)', type: 'json', parent: 'claude', placeholder: '{"PreToolUse": [{"matcher": "Bash(git commit)", "hooks": [...]}]}', help: '高级功能：用 JSON 配置在特定时机（如执行某命令前后）自动运行的钩子脚本。', platforms: ['claude'] },
  // WorkBuddy（腾讯 CodeBuddy 生态）marketplace 风格 frontmatter 字段（均带回退）。
  { key: 'displayName', label: '显示名称 (display_name)', type: 'text', parent: 'workbuddy', placeholder: '人类友好的中文标题', help: 'WorkBuddy 市场中展示的主标题（中文）。留空则回退使用通用「显示名称」或 Skill 名称。', platforms: ['workbuddy'] },
  { key: 'displayNameEn', label: '英文显示名称 (display_name_en)', type: 'text', parent: 'workbuddy', placeholder: 'Human-friendly English title', help: 'WorkBuddy 市场中展示的英文标题。留空则不输出该字段。', platforms: ['workbuddy'] },
  { key: 'descriptionZh', label: '中文描述 (description_zh)', type: 'textarea', parent: 'workbuddy', placeholder: '一句话中文描述', help: 'WorkBuddy 市场中的中文描述。留空则回退使用通用「描述」。', platforms: ['workbuddy'] },
  { key: 'descriptionEn', label: '英文描述 (description_en)', type: 'textarea', parent: 'workbuddy', placeholder: 'One-line English description', help: 'WorkBuddy 市场中的英文描述。留空则不输出该字段。', platforms: ['workbuddy'] },
  { key: 'visibility', label: '可见性 (visibility)', type: 'select', parent: 'workbuddy', options: ['', 'public', 'private'], help: '在 WorkBuddy 市场中的可见性：public 公开 / private 私有。留空则默认 public。', platforms: ['workbuddy'] },
]

const commonFields = [
  { key: 'name', label: '名称 (ID)', editable: false },
  { key: 'description', label: '描述', editable: true },
  { key: 'policy.auto_invoke', label: '允许自动激活', editable: true, type: 'boolean' },
  { key: 'dependencies.skills', label: '依赖 Skills', editable: true },
  { key: 'resources', label: '资源 (scripts/references/assets)', editable: true },
  { key: 'metadata.version', label: '版本', editable: true },
  { key: 'metadata.author', label: '作者', editable: true },
  { key: 'metadata.license', label: '许可证', editable: true },
  { key: 'metadata.tags', label: '标签', editable: true },
]

function getFieldValue(field: FieldDef): string {
  if (!cfg.value) return ''
  const parentObj = cfg.value[field.parent] as Record<string, any> | undefined
  if (!parentObj) return ''
  const val = parentObj[field.key]
  if (Array.isArray(val)) return val.join(', ')
  return val ?? ''
}

function setFieldValue(field: FieldDef, val: string) {
  if (field.type === 'tags') {
    setNestedField(field.parent, field.key, val.split(',').map((s) => s.trim()).filter(Boolean))
  } else if (field.type === 'select' || field.type === 'text' || field.type === 'path') {
    // 清空 → 发 null 删除标记（后端按 null 删键）。不能发 undefined：JSON.stringify 会丢键，
    // 后端浅合并就删不掉旧值。
    setNestedField(field.parent, field.key, val === '' ? null : val)
  } else {
    setNestedField(field.parent, field.key, val)
  }
}

// boolean 字段用三态下拉：未设置 / true / false（避免默认 false 误伤 Claude 默认 true）
function getTriValue(field: FieldDef): string {
  if (!cfg.value) return ''
  const parentObj = cfg.value[field.parent] as Record<string, any> | undefined
  const val = parentObj?.[field.key]
  if (val === true) return 'true'
  if (val === false) return 'false'
  return ''
}

function setTriValue(field: FieldDef, val: string) {
  // "未设置" → null 删除标记（理由同 setFieldValue）。
  setNestedField(field.parent, field.key, val === 'true' ? true : val === 'false' ? false : null)
}

// json 字段（如 Claude hooks）以格式化文本编辑，保存时解析回对象
function getJsonValue(field: FieldDef): string {
  if (!cfg.value) return ''
  const parentObj = cfg.value[field.parent] as Record<string, any> | undefined
  const val = parentObj?.[field.key]
  if (val === undefined || val === null || val === '') return ''
  return JSON.stringify(val, null, 2)
}

function setJsonValue(field: FieldDef, val: string) {
  const trimmed = val.trim()
  if (!trimmed) {
    // 清空 → null 删除标记（理由同 setFieldValue）。
    setNestedField(field.parent, field.key, null)
    return
  }
  try {
    setNestedField(field.parent, field.key, JSON.parse(trimmed))
  } catch {
    /* 解析失败时保留原值，不写入 */
  }
}

function getToolsJson(): string {
  if (!cfg.value) return '[]'
  return JSON.stringify(cfg.value.dependencies?.tools ?? [], null, 2)
}

function setToolsJson(val: string) {
  try {
    setNestedField('dependencies', 'tools', JSON.parse(val || '[]'))
  } catch {
    /* ignore parse error */
  }
}

interface PlatformMeta {
  name: string
  color: string
  badge: string
  desc: string
  descMore?: string
}

const platformMeta: Record<string, PlatformMeta> = {
  codex: {
    name: 'Codex',
    color: '#10b981',
    badge: 'openai.yaml',
    desc: 'Codex 通过 agents/openai.yaml 文件描述 Skill 的界面展示、策略和工具依赖。',
  },
  cursor: {
    name: 'Cursor',
    color: '#6366f1',
    badge: 'SKILL.md frontmatter',
    desc: 'Cursor 将策略写入 SKILL.md frontmatter，支持 surfaces 限定展示界面。不支持 UI 元数据。',
  },
  windsurf: {
    name: 'Windsurf',
    color: '#06b6d4',
    badge: 'SKILL.md frontmatter',
    desc: 'Windsurf (Cascade) 与 Cursor 同构'
  },
  claude: {
    name: 'Claude Code',
    color: '#d97757',
    badge: 'SKILL.md frontmatter (标准 + 运行时扩展)',
    desc: 'Claude Code 采用 Agent Skills 标准并扩展运行时字段',
    descMore: '标准元数据（license/compatibility/author/version）与 Claude 专有字段（allowed-tools / model / effort / context / agent / hooks 等）全部写入同一 SKILL.md frontmatter，无独立元数据文件。项目级落 .claude/skills/，全局级落 ~/.claude/skills/。',
  },
  kiro: {
    name: 'Kiro',
    color: '#7c3aed',
    badge: 'SKILL.md frontmatter (Agent Skills 标准核心)',
    desc: 'Kiro 遵循开放 Agent Skills 标准',
  },
  trae: {
    name: 'Trae',
    color: '#ec4899',
    badge: 'SKILL.md frontmatter (仅 name + description)',
    desc: 'Trae（字节）原生支持开放 Agent Skills 标准',
  },
  qoder: {
    name: 'Qoder',
    color: '#f59e0b',
    badge: 'SKILL.md frontmatter (仅 name + description)',
    desc: 'Qoder（阿里）原生支持开放 Agent Skills 标准',
  },
  workbuddy: {
    name: 'WorkBuddy',
    color: '#1e6fff',
    badge: 'SKILL.md frontmatter (marketplace 风格)',
    desc: 'WorkBuddy（腾讯 CodeBuddy 生态）遵循开放 Agent Skills 标准，并扩展 marketplace 风格字段',
    descMore: '在 name + description 之外，输出 version / display_name / display_name_en / description_zh / description_en / visibility（均带回退，无平台特有必填项）。市场安装态边文件 _skillhub_meta.json / _icon.svg 为发布/安装产物，部署时不生成。项目级落 .workbuddy/skills/，全局级落 ~/.workbuddy/skills/。',
  },
}

const fieldsForPlatform = computed(() => {
  if (activePlatform.value === 'overview') return []
  return allFields.filter((f) => f.platforms.includes(activePlatform.value as any))
})

// 各平台构建说明（点击平台图标弹窗展示）。内容含 <code> 标记，以 v-html 渲染。
const buildInfo: Record<string, string[]> = {
  codex: [
    '输出含 <code>SKILL.md</code>（frontmatter: name + description，可选 metadata.short-description）的文件夹',
    '界面展示、默认提示词与 MCP 工具依赖写入 <code>agents/openai.yaml</code>（interface / dependencies.tools / policy）',
    '可携带 <code>scripts</code> / <code>references</code> / <code>assets</code> 资源目录',
    '部署目录：<code>~/.codex/skills/{name}/</code>（可由 CODEX_HOME 覆盖）',
  ],
  cursor: [
    '<code>policy.auto_invoke: false</code> → 输出 <code>disable-model-invocation: true</code>',
    '不包含 UI 元数据、MCP 工具声明和 LICENSE 文件',
    '图标文件 (icon_small / icon_large) 在构建时被丢弃',
  ],
  windsurf: [
    '与 Cursor 同构：输出含 <code>SKILL.md</code>（frontmatter: name + description）的文件夹',
    '项目级落 <code>.windsurf/skills/{id}/</code>；全局级落 <code>~/.codeium/windsurf/skills/{id}/</code>',
    '不包含 UI 元数据、MCP 工具声明；无平台特有必填字段',
  ],
  claude: [
    '标准元数据 + Claude 专有字段全部写入同一 <code>SKILL.md</code> frontmatter，无独立 <code>openai.yaml</code>',
    '<code>policy.auto_invoke: false</code> → 输出 <code>disable-model-invocation: true</code>（与 Cursor 同义）',
    '<code>context: fork</code> 时 <code>agent</code> 才生效；<code>user-invocable</code> 仅在为 <code>false</code> 时输出',
    '<code>metadata</code>（license / compatibility / author / version）随构建写入 frontmatter',
    '部署目标：项目级 <code>.claude/skills/{id}/</code>，全局级 <code>~/.claude/skills/{id}/</code>',
  ],
  kiro: [
    '遵循开放 Agent Skills 标准：输出含 <code>SKILL.md</code>（frontmatter: name + description）的文件夹',
    '标准可选字段 <code>license</code> / <code>compatibility</code> / <code>metadata</code>(author/version) 有值才写入 frontmatter（属通用元数据，在 Skill Forge 中编辑）',
    '不含 Claude 运行时扩展（model / effort / context / hooks / allowed-tools 等）与 Codex 的 UI 元数据；无独立 <code>openai.yaml</code> / <code>LICENSE.txt</code>',
    '项目级落 <code>.kiro/skills/{id}/</code>；全局级落 <code>~/.kiro/skills/{id}/</code>',
  ],
  trae: [
    '与 Windsurf 同源：输出含 <code>SKILL.md</code>（frontmatter 官方仅 name + description）的文件夹',
    '严格只输出这两个字段，其余平台特有字段（UI / 运行时 / metadata 等）全部丢弃，忠于 Trae 官方规范',
    '可携带 <code>scripts</code> / <code>references</code> / <code>assets</code>；无独立 <code>openai.yaml</code> / <code>LICENSE.txt</code>',
    '项目级落 <code>.trae/skills/{id}/</code>；全局级在 <code>~/.trae/skills/{id}/</code>（国际版）与 <code>~/.trae-cn/skills/{id}/</code>（国内版）间自动探测',
  ],
  qoder: [
    '与 Windsurf / Trae 同源：输出含 <code>SKILL.md</code>（frontmatter 官方仅 name + description）的文件夹',
    '严格只输出这两个字段，其余平台特有字段（UI / 运行时 / metadata 等）全部丢弃，忠于 Qoder 官方规范',
    '可携带 <code>scripts</code> / <code>references</code> / <code>assets</code>；无独立 <code>openai.yaml</code> / <code>LICENSE.txt</code>',
    '项目级落 <code>.qoder/skills/{id}/</code>；全局级落 <code>~/.qoder/skills/{id}/</code>（统一目录，无国内/国际分叉），项目级优先于全局级',
  ],
  workbuddy: [
    '输出含 <code>SKILL.md</code> 的文件夹，frontmatter 为 marketplace 风格：<code>name</code> / <code>description</code> / <code>version</code> / <code>display_name</code> / <code>display_name_en</code> / <code>description_zh</code> / <code>description_en</code> / <code>visibility</code>',
    '新增字段取自抽象包 <code>workbuddy</code> 块并带回退：<code>display_name</code> ← displayName/通用显示名/name；<code>description_zh</code> ← description；<code>visibility</code> ← public；<code>_en</code> 缺省时省略',
    '<strong>不</strong>生成 <code>_skillhub_meta.json</code> / <code>_icon.svg</code>（市场发布/安装态产物，含无法本地伪造的 skillId/source；WorkBuddy 加载只读 SKILL.md frontmatter）',
    '可携带 <code>scripts</code> / <code>references</code> / <code>assets</code>；项目级落 <code>.workbuddy/skills/{id}/</code>，全局级落 <code>~/.workbuddy/skills/{id}/</code>（统一目录，无国内/国际分叉），项目级优先于全局级',
  ],
}

const showBuildModal = ref(false)
function openBuildModal() {
  if (buildInfo[activePlatform.value]) showBuildModal.value = true
}
// 切换平台时关闭弹窗，避免内容错位
watch(activePlatform, () => {
  showBuildModal.value = false
})
</script>

<template>
  <div class="ps-panel">
    <!-- Platform Segmented Control -->
    <nav class="segment-nav">
      <button :class="['seg-btn', { active: activePlatform === 'overview' }]" @click="activePlatform = 'overview'">
        <svg class="seg-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="3" width="7" height="7" rx="1.5" />
          <rect x="14" y="3" width="7" height="7" rx="1.5" />
          <rect x="3" y="14" width="7" height="7" rx="1.5" />
          <rect x="14" y="14" width="7" height="7" rx="1.5" />
        </svg>
        总览
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'codex' }]" @click="activePlatform = 'codex'">
        <img class="seg-icon" :src="platformIcons.codex" alt="" aria-hidden="true" />
        Codex
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'cursor' }]" @click="activePlatform = 'cursor'">
        <img class="seg-icon" :src="platformIcons.cursor" alt="" aria-hidden="true" />
        Cursor
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'windsurf' }]" @click="activePlatform = 'windsurf'">
        <img class="seg-icon" :src="platformIcons.windsurf" alt="" aria-hidden="true" />
        Windsurf
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'claude' }]" @click="activePlatform = 'claude'">
        <img class="seg-icon" :src="platformIcons.claude" alt="" aria-hidden="true" />
        Claude Code
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'kiro' }]" @click="activePlatform = 'kiro'">
        <img class="seg-icon" :src="platformIcons.kiro" alt="" aria-hidden="true" />
        Kiro
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'trae' }]" @click="activePlatform = 'trae'">
        <img class="seg-icon" :src="platformIcons.trae" alt="" aria-hidden="true" />
        Trae
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'qoder' }]" @click="activePlatform = 'qoder'">
        <img class="seg-icon" :src="platformIcons.qoder" alt="" aria-hidden="true" />
        Qoder
      </button>
      <button :class="['seg-btn', { active: activePlatform === 'workbuddy' }]" @click="activePlatform = 'workbuddy'">
        <img class="seg-icon" :src="platformIcons.workbuddy" alt="" aria-hidden="true" />
        WorkBuddy
      </button>
    </nav>

    <!-- Overview: field matrix -->
    <section v-if="activePlatform === 'overview'" class="overview-section">
      <!-- Common fields table -->
      <div class="field-table-wrapper">
        <h3>
          通用字段
          <span class="help-tip" tabindex="0" role="button" aria-label="说明">
            <svg class="help-tip-icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="18" height="18" aria-hidden="true">
              <path d="M464 784.352c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z" fill="currentColor"></path>
              <path d="M512 960C264.96 960 64 759.04 64 512S264.96 64 512 64s448 200.96 448 448-200.96 448-448 448z m0-831.713c-211.584 0-383.713 172.129-383.713 383.713 0 211.552 172.129 383.713 383.713 383.713 211.552 0 383.713-172.16 383.713-383.713 0-211.584-172.161-383.713-383.713-383.713z" fill="currentColor"></path>
              <path d="M512 673.695c-17.665 0-32-14.336-32-31.999v-54.112c0-52.353 39.999-92.352 75.327-127.648 25.887-25.92 52.672-52.672 52.672-74.016 0-53.344-43.072-96.736-95.999-96.736-53.823 0-96 41.536-96 94.56 0 17.664-14.335 31.999-32 31.999s-32-14.336-32-32c0-87.423 71.774-158.559 160-158.559S672 297.28 672 385.92c0 47.904-36.32 84.191-71.424 119.296-27.84 27.776-56.575 56.512-56.575 82.335v54.112c0 17.665-14.336 32.032-32.001 32.032z" fill="currentColor"></path>
            </svg>
            <span class="help-tip-bubble" role="tooltip">这些是所有平台都支持的基础信息（比如名称、描述）。在 Skill 编辑器里填写一次，导出到任何一个平台都会自动带上，不用为每个平台单独再填一遍。</span>
          </span>
        </h3>
        <div class="field-table-card">
        <table class="field-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>Codex</th>
              <th>Cursor</th>
              <th>Windsurf</th>
              <th>Claude Code</th>
              <th>Kiro</th>
              <th>Trae</th>
              <th>Qoder</th>
              <th>WorkBuddy</th>
              <th>说明</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="f in commonFields" :key="f.key">
              <td class="field-name">{{ f.label }}</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="field-note">{{ f.editable ? '可在 Skill 编辑器中编辑' : '创建时确定' }}</td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>

      <!-- Platform-specific fields table -->
      <div class="field-table-wrapper">
        <h3>
          平台特有字段
          <span class="help-tip" tabindex="0" role="button" aria-label="说明">
            <svg class="help-tip-icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="18" height="18" aria-hidden="true">
              <path d="M464 784.352c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z" fill="currentColor"></path>
              <path d="M512 960C264.96 960 64 759.04 64 512S264.96 64 512 64s448 200.96 448 448-200.96 448-448 448z m0-831.713c-211.584 0-383.713 172.129-383.713 383.713 0 211.552 172.129 383.713 383.713 383.713 211.552 0 383.713-172.16 383.713-383.713 0-211.584-172.161-383.713-383.713-383.713z" fill="currentColor"></path>
              <path d="M512 673.695c-17.665 0-32-14.336-32-31.999v-54.112c0-52.353 39.999-92.352 75.327-127.648 25.887-25.92 52.672-52.672 52.672-74.016 0-53.344-43.072-96.736-95.999-96.736-53.823 0-96 41.536-96 94.56 0 17.664-14.335 31.999-32 31.999s-32-14.336-32-32c0-87.423 71.774-158.559 160-158.559S672 297.28 672 385.92c0 47.904-36.32 84.191-71.424 119.296-27.84 27.776-56.575 56.512-56.575 82.335v54.112c0 17.665-14.336 32.032-32.001 32.032z" fill="currentColor"></path>
            </svg>
            <span class="help-tip-bubble" role="tooltip">这些是只有部分平台才支持的额外信息。下表中打勾（✓）的平台导出时会带上对应内容，打叉（✗）的平台会自动忽略——填了也不会出错，只是在不支持的平台上不生效。</span>
          </span>
        </h3>
        <div class="field-table-card">
        <table class="field-table">
          <thead>
            <tr>
              <th>字段</th>
              <th>Codex</th>
              <th>Cursor</th>
              <th>Windsurf</th>
              <th>Claude</th>
              <th>Kiro</th>
              <th>Trae</th>
              <th>Qoder</th>
              <th>WorkBuddy</th>
              <th>构建映射</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="field-name">ui.display_name</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml interface.display_name</td>
            </tr>
            <tr>
              <td class="field-name">ui.short_description</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml interface.short_description</td>
            </tr>
            <tr>
              <td class="field-name">ui.brand_color</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml interface.brand_color</td>
            </tr>
            <tr>
              <td class="field-name">ui.default_prompt</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml interface.default_prompt</td>
            </tr>
            <tr>
              <td class="field-name">ui.icon_small / icon_large</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml interface.icon_*</td>
            </tr>
            <tr>
              <td class="field-name">dependencies.tools (MCP)</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ openai.yaml dependencies.tools</td>
            </tr>
            <tr>
              <td class="field-name">metadata.surfaces</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ SKILL.md frontmatter metadata.surfaces</td>
            </tr>
            <tr>
              <td class="field-name">metadata.license</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">Codex → LICENSE.txt；Claude / Kiro → frontmatter license</td>
            </tr>
            <tr>
              <td class="field-name">metadata.compatibility / author / version</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ SKILL.md frontmatter compatibility / metadata</td>
            </tr>
            <tr>
              <td class="field-name">claude.allowed_tools / disallowed_tools</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ frontmatter allowed-tools / disallowed-tools</td>
            </tr>
            <tr>
              <td class="field-name">claude.model / effort</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ frontmatter model / effort</td>
            </tr>
            <tr>
              <td class="field-name">claude.context / agent</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ frontmatter context (仅 fork) / agent</td>
            </tr>
            <tr>
              <td class="field-name">claude.user_invocable / argument_hint</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ frontmatter user-invocable (仅 false) / argument-hint</td>
            </tr>
            <tr>
              <td class="field-name">claude.when_to_use / hooks</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="field-note">→ frontmatter when_to_use / hooks</td>
            </tr>
            <tr>
              <td class="field-name">workbuddy.displayName / displayNameEn</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="field-note">→ frontmatter display_name / display_name_en（缺省回退 name）</td>
            </tr>
            <tr>
              <td class="field-name">workbuddy.descriptionZh / descriptionEn</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="field-note">→ frontmatter description_zh / description_en（zh 缺省回退 description）</td>
            </tr>
            <tr>
              <td class="field-name">workbuddy.visibility</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support no">✗</td>
              <td class="support yes">✓</td>
              <td class="field-note">→ frontmatter visibility（缺省回退 public）</td>
            </tr>
          </tbody>
        </table>
        </div>
      </div>
    </section>

    <!-- Platform-specific editor -->
    <section v-else class="platform-detail-section">
      <div class="platform-info-bar">
        <button
          type="button"
          class="platform-info-icon-btn"
          @click="openBuildModal"
          :aria-label="`查看 ${platformMeta[activePlatform].name} 构建说明`"
          title="点击查看构建说明"
        >
          <img class="platform-info-icon" :src="platformIcons[activePlatform]" alt="" aria-hidden="true" />
        </button>
        <div class="platform-info-text">
          <h2 class="platform-name">{{ platformMeta[activePlatform].name }}</h2>
          <p class="platform-desc">
            {{ platformMeta[activePlatform].desc }}
            <span
              v-if="platformMeta[activePlatform].descMore"
              class="help-tip"
              tabindex="0"
              role="button"
              aria-label="详细说明"
            >
              <svg class="help-tip-icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="15" height="15" aria-hidden="true">
                <path d="M464 784.352c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z" fill="currentColor"></path>
                <path d="M512 960C264.96 960 64 759.04 64 512S264.96 64 512 64s448 200.96 448 448-200.96 448-448 448z m0-831.713c-211.584 0-383.713 172.129-383.713 383.713 0 211.552 172.129 383.713 383.713 383.713 211.552 0 383.713-172.16 383.713-383.713 0-211.584-172.161-383.713-383.713-383.713z" fill="currentColor"></path>
                <path d="M512 673.695c-17.665 0-32-14.336-32-31.999v-54.112c0-52.353 39.999-92.352 75.327-127.648 25.887-25.92 52.672-52.672 52.672-74.016 0-53.344-43.072-96.736-95.999-96.736-53.823 0-96 41.536-96 94.56 0 17.664-14.335 31.999-32 31.999s-32-14.336-32-32c0-87.423 71.774-158.559 160-158.559S672 297.28 672 385.92c0 47.904-36.32 84.191-71.424 119.296-27.84 27.776-56.575 56.512-56.575 82.335v54.112c0 17.665-14.336 32.032-32.001 32.032z" fill="currentColor"></path>
              </svg>
              <span class="help-tip-bubble" role="tooltip">{{ platformMeta[activePlatform].descMore }}</span>
            </span>
          </p>
        </div>
      </div>

      <!-- No skill selected -->
      <div v-if="!store.currentId" class="no-skill-hint">
        请先选择一个 Skill，然后回到此处编辑平台特有字段。
      </div>

      <!-- Platforms without platform-specific fields -->
      <div v-else-if="fieldsForPlatform.length === 0" class="no-fields-hint">
        该平台没有平台特有字段，导出内容均来自「通用字段」。点击上方平台图标可查看该平台的构建说明。
      </div>

      <!-- Editable fields (Cursor / Codex / Claude) -->
      <div v-else class="platform-fields">
        <div v-for="field in fieldsForPlatform" :key="field.key" class="pf-field-row">
          <label>
            {{ field.label }}
            <span v-if="field.help" class="help-tip" tabindex="0" role="button" aria-label="说明">
              <svg class="help-tip-icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="15" height="15" aria-hidden="true">
                <path d="M464 784.352c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z" fill="currentColor"></path>
                <path d="M512 960C264.96 960 64 759.04 64 512S264.96 64 512 64s448 200.96 448 448-200.96 448-448 448z m0-831.713c-211.584 0-383.713 172.129-383.713 383.713 0 211.552 172.129 383.713 383.713 383.713 211.552 0 383.713-172.16 383.713-383.713 0-211.584-172.161-383.713-383.713-383.713z" fill="currentColor"></path>
                <path d="M512 673.695c-17.665 0-32-14.336-32-31.999v-54.112c0-52.353 39.999-92.352 75.327-127.648 25.887-25.92 52.672-52.672 52.672-74.016 0-53.344-43.072-96.736-95.999-96.736-53.823 0-96 41.536-96 94.56 0 17.664-14.335 31.999-32 31.999s-32-14.336-32-32c0-87.423 71.774-158.559 160-158.559S672 297.28 672 385.92c0 47.904-36.32 84.191-71.424 119.296-27.84 27.776-56.575 56.512-56.575 82.335v54.112c0 17.665-14.336 32.032-32.001 32.032z" fill="currentColor"></path>
              </svg>
              <span class="help-tip-bubble" role="tooltip">{{ field.help }}</span>
            </span>
          </label>
          <div v-if="field.type === 'color'" class="color-row">
            <input
              type="color"
              :value="getFieldValue(field) || '#3B82F6'"
              @input="setFieldValue(field, ($event.target as HTMLInputElement).value)"
              class="color-picker"
            />
            <input
              :value="getFieldValue(field)"
              @input="setFieldValue(field, ($event.target as HTMLInputElement).value)"
              class="form-input"
              :placeholder="field.placeholder"
            />
          </div>
          <BaseSelect
            v-else-if="field.type === 'select'"
            :model-value="getFieldValue(field)"
            :options="(field.options || []).map((opt) => ({ value: opt, label: opt || '未设置（默认）' }))"
            @update:model-value="setFieldValue(field, String($event))"
          />
          <BaseSelect
            v-else-if="field.type === 'boolean'"
            :model-value="getTriValue(field)"
            :options="[
              { value: '', label: '未设置（默认 true）' },
              { value: 'true', label: 'true' },
              { value: 'false', label: 'false' },
            ]"
            @update:model-value="setTriValue(field, String($event))"
          />
          <textarea
            v-else-if="field.type === 'textarea'"
            :value="getFieldValue(field)"
            @input="setFieldValue(field, ($event.target as HTMLTextAreaElement).value)"
            class="form-input textarea"
            rows="3"
            :placeholder="field.placeholder"
          ></textarea>
          <textarea
            v-else-if="field.type === 'json'"
            :value="getJsonValue(field)"
            @change="setJsonValue(field, ($event.target as HTMLTextAreaElement).value)"
            class="form-input textarea code-area"
            rows="6"
            spellcheck="false"
            :placeholder="field.placeholder"
          ></textarea>
          <FolderPicker
            v-else-if="field.type === 'path'"
            :model-value="getFieldValue(field)"
            :placeholder="field.placeholder"
            @update:model-value="setFieldValue(field, $event)"
          />
          <input
            v-else
            :value="getFieldValue(field)"
            @input="setFieldValue(field, ($event.target as HTMLInputElement).value)"
            class="form-input"
            :placeholder="field.placeholder"
          />
        </div>

        <!-- Codex: MCP tools (special JSON field) -->
        <div v-if="activePlatform === 'codex'" class="pf-field-row">
          <label>
            MCP 工具依赖 (dependencies.tools)
            <span class="help-tip" tabindex="0" role="button" aria-label="说明">
              <svg class="help-tip-icon" viewBox="0 0 1024 1024" version="1.1" xmlns="http://www.w3.org/2000/svg" width="15" height="15" aria-hidden="true">
                <path d="M464 784.352c0 26.51 21.49 48 48 48s48-21.49 48-48-21.49-48-48-48-48 21.49-48 48z" fill="currentColor"></path>
                <path d="M512 960C264.96 960 64 759.04 64 512S264.96 64 512 64s448 200.96 448 448-200.96 448-448 448z m0-831.713c-211.584 0-383.713 172.129-383.713 383.713 0 211.552 172.129 383.713 383.713 383.713 211.552 0 383.713-172.16 383.713-383.713 0-211.584-172.161-383.713-383.713-383.713z" fill="currentColor"></path>
                <path d="M512 673.695c-17.665 0-32-14.336-32-31.999v-54.112c0-52.353 39.999-92.352 75.327-127.648 25.887-25.92 52.672-52.672 52.672-74.016 0-53.344-43.072-96.736-95.999-96.736-53.823 0-96 41.536-96 94.56 0 17.664-14.335 31.999-32 31.999s-32-14.336-32-32c0-87.423 71.774-158.559 160-158.559S672 297.28 672 385.92c0 47.904-36.32 84.191-71.424 119.296-27.84 27.776-56.575 56.512-56.575 82.335v54.112c0 17.665-14.336 32.032-32.001 32.032z" fill="currentColor"></path>
              </svg>
              <span class="help-tip-bubble" role="tooltip">声明该 Skill 依赖的 MCP 工具（如外部服务接口），用 JSON 数组填写；构建时写入 openai.yaml 的 dependencies.tools。</span>
            </span>
          </label>
          <textarea
            :value="getToolsJson()"
            @change="setToolsJson(($event.target as HTMLTextAreaElement).value)"
            class="form-input textarea code-area"
            rows="8"
            spellcheck="false"
            placeholder='[{"type": "mcp", "name": "github", "transport": "streamable_http", "url": "https://..."}]'
          ></textarea>
        </div>

      </div>

      <!-- Build info modal (triggered by clicking the platform icon) -->
      <BaseModal v-model="showBuildModal" :title="`${platformMeta[activePlatform].name} · 构建说明`" :width="520">
        <div class="build-modal-titlebar">
          <img class="build-modal-icon" :src="platformIcons[activePlatform]" alt="" aria-hidden="true" />
          <span>{{ platformMeta[activePlatform].name }}</span>
        </div>
        <ul class="build-modal-list">
          <li v-for="(item, i) in (buildInfo[activePlatform] || [])" :key="i" v-html="item"></li>
        </ul>
      </BaseModal>
    </section>
  </div>
</template>

<style scoped>
.ps-panel {
  width: 100%;
}

/* 平台导航：独立文字按钮，激活项使用浅灰色悬浮块 */
.segment-nav {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.35rem;
  margin-bottom: 1.75rem;
}

.seg-btn {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  padding: 0.55rem 1.15rem;
  background: transparent;
  border: none;
  border-radius: 12px;
  color: #6b7280;
  font-size: 1.02rem;
  font-weight: 500;
  font-family: inherit;
  -webkit-tap-highlight-color: transparent;
  cursor: pointer;
  transition: color 0.18s ease, background-color 0.18s ease, box-shadow 0.18s ease;
}

.seg-btn:hover { color: #151717; }
.seg-btn:hover:not(.active) { background: #f6f7fa; }

.seg-btn.active {
  color: #151717;
  font-weight: 600;
  background: #eef0f3;
  box-shadow: 0 3px 10px rgba(47, 51, 66, 0.1);
}

.seg-icon {
  width: 22px;
  height: 22px;
  flex-shrink: 0;
  object-fit: contain;
  filter: grayscale(0.35);
  opacity: 0.7;
  transition: filter 0.15s ease, opacity 0.15s ease;
}
.seg-btn:hover .seg-icon,
.seg-btn.active .seg-icon {
  filter: none;
  opacity: 1;
}
/* 总览为更紧凑的线性图标，跟随文字色 */
svg.seg-icon { width: 18px; height: 18px; color: inherit; filter: none; }

/* Overview */
.overview-intro {
  margin-bottom: 2rem;
  font-size: 0.82rem;
  color: #6b7280;
  line-height: 1.7;
}
.overview-intro strong { color: #151717; }

.field-table-wrapper {
  margin-bottom: 2.5rem;
}

.field-table-card {
  background: #ffffff;
  border: none;
  border-radius: 0;
  overflow-x: auto;
}
.field-table-wrapper h3 {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 1.18rem;
  font-weight: 600;
  color: #2f3342;
  margin-bottom: 0.9rem;
}

/* Help tooltip */
.help-tip {
  position: relative;
  display: inline-flex;
  align-items: center;
  vertical-align: middle;
  color: #9ca3af;
  cursor: help;
  outline: none;
}
.platform-desc .help-tip {
  top: -2px;
}
.help-tip:hover,
.help-tip:focus {
  color: #6b7280;
}
.help-tip-icon {
  display: block;
}
.help-tip-bubble {
  position: absolute;
  top: calc(100% + 8px);
  left: 0;
  z-index: 20;
  width: max-content;
  max-width: 320px;
  padding: 0.6rem 0.75rem;
  border-radius: 8px;
  background: #1f2328;
  color: #f3f4f6;
  font-size: 0.78rem;
  font-weight: 400;
  line-height: 1.6;
  letter-spacing: 0;
  text-transform: none;
  box-shadow: 0 6px 20px rgba(0, 0, 0, 0.18);
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: opacity 0.15s ease, transform 0.15s ease, visibility 0.15s;
}
.help-tip-bubble::before {
  content: '';
  position: absolute;
  bottom: 100%;
  left: 10px;
  border: 6px solid transparent;
  border-bottom-color: #1f2328;
}
.help-tip:hover .help-tip-bubble,
.help-tip:focus .help-tip-bubble,
.help-tip:focus-within .help-tip-bubble {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}

.field-table {
  width: 100%;
  min-width: 980px;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 0.88rem;
}

/* Let the last column (说明 / 构建映射) absorb extra width so the
   first column hugs its content and sits close to the platform columns. */
.field-table th:last-child,
.field-table td.field-note {
  width: 100%;
}

.field-table th {
  text-align: left;
  padding: 0.78rem 1rem;
  background: #e8ebf0;
  font-weight: 600;
  font-size: 0.78rem;
  letter-spacing: 0.01em;
  color: #5f6677;
  border-bottom: 1px solid #e2e6ec;
  white-space: nowrap;
}

.field-table th:not(:first-child):not(:last-child) {
  text-align: center;
}

.field-table th:first-child,
.field-table td:first-child {
  min-width: 210px;
}

.field-table td {
  padding: 0.76rem 1rem;
  color: #5f6677;
  border-bottom: 1px solid #edf0f4;
  vertical-align: middle;
  transition: background-color 0.15s ease;
}

.field-table tbody tr:last-child td {
  border-bottom: none;
}

.field-table tbody tr:hover td {
  background: #eef0f3;
}

.field-name {
  font-weight: 600;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.82rem;
  color: #2f3342;
}

.field-note {
  min-width: 260px;
  color: #8a93a5;
  font-size: 0.8rem;
  line-height: 1.5;
}

.support {
  text-align: center;
  width: 72px;
  font-size: 1rem;
  font-weight: 700;
}
.support.yes { color: #16a34a; }
.support.no { color: #b6bdc9; opacity: 1; }

/* Platform Detail */
.platform-info-bar {
  display: flex;
  align-items: center;
  gap: 1rem;
  padding: 0 1.5rem;
  background: transparent;
  border: none;
  border-radius: 12px;
  margin-bottom: 0;
}

.platform-info-icon-btn {
  flex-shrink: 0;
  padding: 0;
  border: none;
  background: transparent;
  border-radius: 12px;
  cursor: pointer;
  display: inline-flex;
  -webkit-tap-highlight-color: transparent;
  transition: transform 0.15s ease;
}
.platform-info-icon-btn:hover { transform: scale(1.06); }
.platform-info-icon-btn:focus-visible { outline: 2px solid #6366f1; outline-offset: 3px; }

.platform-info-icon {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  object-fit: contain;
}

.platform-info-text {
  display: flex;
  flex-direction: column;
  gap: 0;
}

.platform-name {
  font-size: 1.5rem;
  font-weight: 700;
  color: #151717;
  line-height: 1;
  margin: 0;
}

.platform-desc { font-size: 0.82rem; color: #6b7280; line-height: 1.35; margin: 0.15rem 0 0; }

.no-skill-hint,
.no-fields-hint {
  text-align: center;
  padding: 3rem 2rem;
  color: #6b7280;
  font-size: 1.02rem;
  line-height: 1.7;
  background: transparent;
  border: 1px dashed #e5e7eb;
  border-radius: 16px;
}

/* Platform editable fields */
.platform-fields {
  background: transparent;
  border: none;
  border-radius: 16px;
  padding: 1.5rem;
}

.pf-field-row {
  margin-bottom: 1rem;
}
.pf-field-row:last-child { margin-bottom: 0; }

.pf-field-row label {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  font-size: 0.92rem;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 0.35rem;
}

.form-input {
  width: 100%;
  padding: 0.68rem 0.85rem;
  background: #eef0f3;
  border: none;
  border-radius: 8px;
  color: #151717;
  font-size: 1rem;
  font-family: inherit;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
  box-sizing: border-box;
}

.form-input:focus {
  outline: none;
  background: #e5e8ed;
  box-shadow: inset 0 0 0 1.5px #151717;
}

.form-input.textarea {
  resize: vertical;
  min-height: 80px;
}

.code-area {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.9rem;
}

.color-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.color-picker {
  width: 34px;
  height: 34px;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  background: transparent;
  padding: 0;
  flex-shrink: 0;
}

.color-picker::-webkit-color-swatch-wrapper {
  padding: 0;
}

.color-picker::-webkit-color-swatch {
  border: 1px solid #d6dae2;
  border-radius: 8px;
}

.color-picker::-moz-color-swatch {
  border: 1px solid #d6dae2;
  border-radius: 8px;
}

.color-picker:focus-visible {
  outline: none;
  box-shadow: none;
}

.color-picker:focus-visible::-webkit-color-swatch {
  border-color: #151717;
  border-width: 1.5px;
}

.color-picker:focus-visible::-moz-color-swatch {
  border-color: #151717;
  border-width: 1.5px;
}

.platform-fields :deep(.bs-trigger),
.platform-fields :deep(.picker-display) {
  border: none;
  background: #eef0f3;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}

.platform-fields :deep(.bs-trigger:hover:not(.disabled)),
.platform-fields :deep(.picker-display:hover) {
  background: #e5e8ed;
}

.platform-fields :deep(.bs-trigger:focus-visible),
.platform-fields :deep(.bs-trigger.open),
.platform-fields :deep(.picker-display:focus-within) {
  border: none;
  background: #e5e8ed;
  box-shadow: inset 0 0 0 1.5px #151717;
}

/* Build info modal */
.build-modal-titlebar {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  margin-bottom: 1rem;
  padding-bottom: 0.85rem;
  border-bottom: 1px solid #ebedf0;
  font-size: 0.95rem;
  font-weight: 600;
  color: #6b7280;
}

.build-modal-icon {
  width: 28px;
  height: 28px;
  flex-shrink: 0;
  object-fit: contain;
}

.build-modal-list {
  list-style: none;
  padding: 0;
  margin: 0;
}

.build-modal-list li {
  position: relative;
  padding: 0.4rem 0 0.4rem 1.1rem;
  font-size: 0.92rem;
  color: #4b5563;
  line-height: 1.65;
}

.build-modal-list li::before {
  content: '•';
  position: absolute;
  left: 0;
  color: #6366f1;
}

.build-modal-list code {
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  padding: 0.12rem 0.4rem;
  border-radius: 4px;
  font-size: 0.85rem;
  font-family: 'JetBrains Mono', monospace;
  color: #151717;
}

@media (max-width: 768px) {
  .segment-nav { overflow-x: auto; }
  .seg-btn { padding: 0.6rem 1rem; font-size: 0.92rem; white-space: nowrap; }
  .field-table { font-size: 0.88rem; }
}
</style>
