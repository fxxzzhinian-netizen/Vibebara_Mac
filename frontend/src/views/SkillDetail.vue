<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getNativeSkill,
  updateNativeSkill,
  deleteNativeSkill,
  listSkillVersions,
  getSkillVersion,
  restoreSkillVersion,
  readVersionResourceFile,
  type NativeSkillDetail,
  type SkillVersionItem,
  type SkillVersionDetail,
  type VersionResourceFileResponse,
  type VersionResourceFileSide,
} from '@/api/skillStore'
import type { ChangeItem } from '@/api/projects'
import { parseUnifiedDiff, inlineSegments } from '@/utils/diffView'
import { formatRelativeTime } from '@/utils/relativeTime'
import type { DiffRow, DiffRowType, InlinePair, SegOp } from '@/utils/diffView'
import { isMockForced, mockVersions, mockVersionDetail, mockResourceFile } from '@/utils/devMockVersions'
import { useTeamStore } from '@/stores/teamStore'
import { useSkillStore } from '@/stores/skillStore'
import { useAuthStore } from '@/stores/authStore'
import { promptInput } from '@/composables/useInputDialog'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { toast } from '@/composables/useToast'
import { useSlideIndicator } from '@/composables/useSlideIndicator'
import { useDirectionalTransition } from '@/composables/useDirectionalTransition'
import AppTopNav from '@/components/AppTopNav.vue'
import HelpTip from '@/components/HelpTip.vue'
import ResourceFilesPanel from '@/components/ResourceFilesPanel.vue'
import PlatformStructurePanel from '@/components/PlatformStructurePanel.vue'
import BaseModal from '@/components/BaseModal.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import SkillIntroPanel from '@/components/SkillIntroPanel.vue'
import { publishSkillToMarket } from '@/api/market'

const route = useRoute()
const router = useRouter()
const teamStore = useTeamStore()
const skillStore = useSkillStore()
const authStore = useAuthStore()

const publishingMarket = ref(false)

const skillId = computed(() => route.params.id as string)
const detail = ref<NativeSkillDetail | null>(null)
const loading = ref(false)
const error = ref('')

type TabKey = 'basic' | 'intro' | 'instructions' | 'resources' | 'metadata' | 'versions' | 'platform'
const activeTab = ref<TabKey>('basic')

// 左侧标签栏黑色滑块：随选中标签纵向平滑滑动到对应位置。
const tabSideRef = ref<HTMLElement | null>(null)
const { style: tabSliderStyle, ready: tabSliderReady } = useSlideIndicator({
  container: tabSideRef,
  activeSelector: '.tab-side-item.active',
  axis: 'y',
  trigger: () => activeTab.value,
})

// 正文随左侧标签纵向滑入滑出：下移标签 → 新内容自下方滑入、旧内容向上滑出，反向则相反。
const {
  name: paneTransition,
  animating: paneAnimating,
  end: paneTransitionEnd,
} = useDirectionalTransition({
  value: () => activeTab.value,
  order: ['basic', 'intro', 'instructions', 'resources', 'metadata', 'versions', 'platform'],
  names: { forward: 'pane-down', backward: 'pane-up' },
})

const cfg = computed(() => (detail.value?.config ?? null) as Record<string, any> | null)
const db = computed(() => detail.value?.db ?? null)
const vibeh = computed(() => detail.value?.vibeh_content ?? '')
const isTeamSkill = computed(() => db.value?.scope === 'team')

// 团队（平台）仓库：所属团队的任意成员均可直接编辑
const isTeamMember = computed(() => {
  const tid = db.value?.team_id
  if (!tid) return false
  return teamStore.teams.some((t) => t.id === tid)
})
const canEdit = computed(() => isTeamSkill.value && isTeamMember.value)

// 编辑态（仅对团队 Skill 开放）
const editing = ref(false)
const saving = ref(false)
const draft = ref<Record<string, any> | null>(null)
const draftVibeh = ref('')

function startEdit() {
  draft.value = JSON.parse(JSON.stringify(cfg.value ?? {}))
  draftVibeh.value = vibeh.value
  editing.value = true
}

function cancelEdit() {
  editing.value = false
  draft.value = null
}

async function handlePublishToMarket() {
  if (!skillId.value || publishingMarket.value) return
  // 介绍页信息已随 Skill 保存在 config.intro，直接发布即可（无需补写弹窗）。
  publishingMarket.value = true
  try {
    const res = await publishSkillToMarket(skillId.value)
    if (res.success) {
      toast.success(
        authStore.user?.is_seed_user ? '已发布到市场' : '已提交审核，等待管理员通过',
      )
    } else {
      toast.error(res.error || '发布失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || '发布失败')
  } finally {
    publishingMarket.value = false
  }
}

function setDraft(key: string, val: unknown) {
  if (!draft.value) return
  draft.value = { ...draft.value, [key]: val }
}

function setDraftNested(parent: string, key: string, val: unknown) {
  if (!draft.value) return
  const cur = (draft.value[parent] as Record<string, unknown>) ?? {}
  draft.value = { ...draft.value, [parent]: { ...cur, [key]: val } }
}

function onResourceEdit(kind: 'scripts' | 'references' | 'assets', val: string) {
  try {
    setDraftNested('resources', kind, JSON.parse(val || '[]'))
  } catch {
    /* 忽略 JSON 解析错误，待用户改正后再保存 */
  }
}

// 保存团队 Skill：先弹应用内确认框询问是否更新版本序列号（替代浏览器 window.confirm）。
const showSaveConfirm = ref(false)

function save() {
  if (!draft.value) return
  showSaveConfirm.value = true
}

// createVersion=true 创建新版本；false 仅保存内容。由确认弹窗的两个按钮分别触发。
async function doSave(createVersion: boolean) {
  if (!draft.value) return
  showSaveConfirm.value = false
  let versionLabel = ''
  if (createVersion) {
    // 应用内输入框（替代 Electron 不支持的 window.prompt）；取消视为不填备注，仍继续保存。
    const label = await promptInput({
      title: '新版本备注',
      message: '可为该版本填写备注/标签，用于在「版本」标签区分版本（可留空）。',
      placeholder: '例如：修复样式 / 调整提示词',
      confirmText: '确定',
      maxlength: 100,
    })
    versionLabel = (label ?? '').trim()
  }
  saving.value = true
  try {
    const res = await updateNativeSkill(skillId.value, draft.value, draftVibeh.value, {
      createVersion,
      versionLabel,
    })
    if (res.success) {
      if (res.no_change) {
        // 未检测到实质改动：不退出编辑、不打扰其他成员，提示后让用户继续编辑
        toast.info('未检测到修改，无需保存')
      } else {
        const summary = res.diff_summary && res.diff_summary !== '无改动' ? res.diff_summary : ''
        const verNote = res.version ? `已创建版本 v${res.version.seq}，` : ''
        toast.success(
          summary
            ? `已保存：${summary}，${verNote}已记入「项目动态」，其他成员可在项目页「更新本地」`
            : `已保存，${verNote}已记入「项目动态」，其他成员可在项目页「更新本地」`,
        )
        editing.value = false
        draft.value = null
        await load()
        if (versionsLoaded.value) await loadVersions()
      }
    } else {
      toast.error(res.error || '保存失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

// ---- 版本记录 ----
const versions = ref<SkillVersionItem[]>([])
const versionsLoading = ref(false)
const versionsLoaded = ref(false)
// 改动明细弹窗：保存当前展示的版本（替代原先的下拉展开）。
const changesVersion = ref<SkillVersionItem | null>(null)
const restoringId = ref('')
const viewingVersion = ref<SkillVersionDetail | null>(null)
const viewLoading = ref(false)
// 开发者模式：?mock=1 / localStorage 强制用模拟数据；dev 构建下真实数据为空/报错时也会自动回退
const devMockForced = isMockForced()
const devMock = ref(devMockForced)

async function loadVersions() {
  // 强制模拟：跳过后端请求，直接填充模拟数据
  if (devMockForced) {
    versions.value = mockVersions()
    versionsLoaded.value = true
    versionsLoading.value = false
    return
  }
  versionsLoading.value = true
  try {
    const res = await listSkillVersions(skillId.value)
    if (res.success) {
      versions.value = res.versions
      versionsLoaded.value = true
    } else if (!import.meta.env.DEV) {
      toast.error(res.error || '加载版本失败')
    }
  } catch (e: any) {
    if (!import.meta.env.DEV) {
      toast.error(e?.response?.data?.detail || e.message || '请求异常')
    }
  } finally {
    versionsLoading.value = false
  }
  // 开发构建：真实版本为空（或请求失败）时回退到模拟数据，便于无数据时调 UI（生产不受影响）
  if (import.meta.env.DEV && versions.value.length === 0) {
    versions.value = mockVersions()
    versionsLoaded.value = true
    devMock.value = true
  }
}

watch(activeTab, (tab) => {
  if (tab === 'versions' && !versionsLoaded.value && !versionsLoading.value) {
    loadVersions()
  }
  // 平台结构面板直接读写 skillStore.currentConfig，进入该标签时按需把当前 Skill 载入 store
  if (tab === 'platform' && skillStore.currentId !== skillId.value) {
    skillStore.selectSkill(skillId.value)
  }
})

// 平台结构改动经 skillStore 暂存（dirty），与基本信息的 draft/版本流相互独立，单独保存。
const platformSaving = ref(false)
async function savePlatform() {
  platformSaving.value = true
  try {
    await skillStore.saveCurrentSkill()
    if (skillStore.error) {
      toast.error(skillStore.error)
    } else {
      toast.success('平台结构已保存')
      await load()
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    platformSaving.value = false
  }
}

function openChanges(v: SkillVersionItem) {
  changesVersion.value = v
}

function closeChanges() {
  changesVersion.value = null
}

// —— 资源文件内容查看（明细弹窗里点击资源文件，叠加一层弹窗看内容/diff）——
interface ResourceViewState {
  path: string
  change: string
  loading: boolean
  error: string
  data: VersionResourceFileResponse | null
}
const resourceView = ref<ResourceViewState | null>(null)

async function openResource(item: ChangeItem) {
  const v = changesVersion.value
  if (!v) return
  const change = item.change || 'modified'
  resourceView.value = { path: item.path, change, loading: true, error: '', data: null }
  // 开发者模式：用模拟内容，跳过后端
  if (devMock.value) {
    resourceView.value = {
      path: item.path,
      change,
      loading: false,
      error: '',
      data: mockResourceFile(item),
    }
    return
  }
  try {
    const res = await readVersionResourceFile(v.skill_id, v.id, item.path)
    if (res.success) {
      resourceView.value = {
        path: item.path,
        change: res.change || change,
        loading: false,
        error: '',
        data: res,
      }
    } else {
      resourceView.value = {
        path: item.path,
        change,
        loading: false,
        error: res.error || '读取失败',
        data: null,
      }
    }
  } catch (e: any) {
    resourceView.value = {
      path: item.path,
      change,
      loading: false,
      error: e?.response?.data?.detail || e.message || '请求异常',
      data: null,
    }
  }
}

function closeResource() {
  resourceView.value = null
}

const rvData = computed(() => resourceView.value?.data ?? null)
const rvNew = computed<VersionResourceFileSide | null>(() => rvData.value?.new ?? null)
const rvOld = computed<VersionResourceFileSide | null>(() => rvData.value?.old ?? null)
const rvChange = computed(() => resourceView.value?.change ?? 'modified')
const rvDiffRows = computed<DiffRow[]>(() => parseUnifiedDiff(rvData.value?.diff || ''))

function isImagePath(p: string): boolean {
  return /\.(png|jpe?g|gif|webp|bmp|ico)$/i.test(p)
}
const rvIsImage = computed(() => isImagePath(resourceView.value?.path ?? ''))

function imageDataUrl(side: VersionResourceFileSide | null, path: string): string {
  if (!side || side.encoding !== 'base64') return ''
  const ext = (path.split('.').pop() || '').toLowerCase()
  const mime = ext === 'jpg' ? 'jpeg' : ext
  return `data:image/${mime};base64,${side.content}`
}

function fmtSize(n?: number): string {
  if (n === undefined || n === null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

async function viewVersion(v: SkillVersionItem) {
  // 开发者模式：直接用模拟详情，跳过后端请求
  if (devMock.value) {
    viewingVersion.value = mockVersionDetail(v)
    return
  }
  viewLoading.value = true
  try {
    const res = await getSkillVersion(skillId.value, v.id)
    if (res.success && res.version) {
      viewingVersion.value = res.version
    } else {
      toast.error(res.error || '查看版本失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '请求异常')
  } finally {
    viewLoading.value = false
  }
}

function closeVersionView() {
  viewingVersion.value = null
}

async function restore(v: SkillVersionItem) {
  const ok = await confirmDialog({
    title: '回滚版本',
    message: `确认回滚到版本 v${v.seq}？\n\n团队仓库内容将被还原为该版本，并生成一条新的回滚版本；其他成员可在项目页「更新本地」拉取。`,
    confirmText: '回滚',
    danger: true,
  })
  if (!ok) return
  // 开发者模式：不调用真实接口，仅提示
  if (devMock.value) {
    toast.info(`（模拟）已回滚到 v${v.seq}`)
    return
  }
  restoringId.value = v.id
  try {
    const res = await restoreSkillVersion(skillId.value, v.id)
    if (res.success) {
      toast.success(
        res.version ? `已回滚到 v${v.seq}（新版本 v${res.version.seq}）` : `已回滚到 v${v.seq}`,
      )
      await load()
      await loadVersions()
    } else {
      toast.error(res.error || '回滚失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '请求异常')
  } finally {
    restoringId.value = ''
  }
}

function sourceLabel(source: string): string {
  const m: Record<string, string> = {
    push: '推送',
    web_edit: '网页编辑',
    restore: '回滚',
  }
  return m[source] || source
}

// —— 改动明细：逐项渲染具体的文件改动位置（字段 inline diff / 正文 unified diff / 资源） ——
function formatVal(v: unknown): string {
  if (v === null || v === undefined || v === '') return '空'
  if (typeof v === 'boolean') return v ? '是' : '否'
  if (Array.isArray(v)) return v.join(', ') || '空'
  return String(v)
}

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

// 表单取值源：编辑态读草稿、查看态读已保存配置；输入框在查看态禁用（与个人编辑器视觉一致）。
const view = computed<Record<string, any>>(() =>
  editing.value && draft.value ? draft.value : (cfg.value ?? {}),
)

async function load() {
  if (!skillId.value) return
  editing.value = false
  draft.value = null
  loading.value = true
  error.value = ''
  try {
    const res = await getNativeSkill(skillId.value)
    if (res.success) {
      detail.value = res
    } else {
      detail.value = null
      error.value = res.error || '加载失败'
    }
  } catch (e: any) {
    detail.value = null
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!teamStore.teams.length) {
    try {
      await teamStore.fetchTeams()
    } catch {
      /* 团队列表加载失败不影响只读查看 */
    }
  }
  await load()
})
watch(skillId, (id) => {
  load()
  // 切换 Skill 时若正停留在平台结构标签，同步刷新 store 让面板跟随当前 Skill
  if (activeTab.value === 'platform' && id) skillStore.selectSkill(id)
})

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push(isTeamSkill.value ? '/team/skills' : '/')
}

// —— 删除 Skill（应用内确认弹窗）——
const showDeleteSkill = ref(false)
const deletingSkill = ref(false)

function askDeleteSkill() {
  showDeleteSkill.value = true
}

async function confirmDeleteSkill() {
  if (deletingSkill.value) return
  deletingSkill.value = true
  try {
    const res = await deleteNativeSkill(skillId.value)
    if (res.success) {
      showDeleteSkill.value = false
      toast.success('已删除该 Skill')
      // 删除后直接回到对应仓库页，避免 router.back() 落到已删除的详情页/空状态白屏
      router.push(isTeamSkill.value ? '/team/skills' : '/')
    } else {
      toast.error('删除失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '删除失败')
  } finally {
    deletingSkill.value = false
  }
}

function timeAgo(ts: string | null | undefined): string {
  return formatRelativeTime(ts, { emptyText: '—', relativeDayLimit: 30 })
}
</script>

<template>
  <div class="forge-page">
    <AppTopNav />

    <div class="forge-main">
      <main class="editor-main">
        <!-- Loading 骨架屏：还原工具栏 + 左侧导航 + 右侧正文的真实布局 -->
        <div v-if="loading" class="detail-skeleton">
          <div class="toolbar">
            <div class="toolbar-left">
              <div class="sk-block sk-back"></div>
              <div class="sk-block sk-title-lg"></div>
              <div class="sk-block sk-chip"></div>
            </div>
            <div class="toolbar-right">
              <div class="sk-block sk-btn"></div>
              <div class="sk-block sk-btn"></div>
            </div>
          </div>
          <div class="editor-body">
            <aside class="tab-side">
              <div v-for="i in 6" :key="i" class="sk-block sk-tab"></div>
            </aside>
            <div class="tab-content">
              <div class="sk-block sk-section-title"></div>
              <div class="sk-block sk-label"></div>
              <div class="sk-block sk-input"></div>
              <div class="sk-block sk-label"></div>
              <div class="sk-block sk-textarea"></div>
            </div>
          </div>
        </div>
        <!-- Error / not found -->
        <div v-else-if="error" class="empty-state">
          <div class="empty-icon">&#9888;</div>
          <p>{{ error }}</p>
          <button class="btn-back-repo" @click="goBack">← 返回</button>
        </div>
        <div v-else-if="!cfg" class="empty-state">
          <div class="empty-icon">&#9881;</div>
          <p>未找到该 Skill</p>
          <button class="btn-back-repo" @click="goBack">← 返回</button>
        </div>

        <!-- Detail -->
        <template v-else>
          <!-- Toolbar -->
          <div class="toolbar">
            <div class="toolbar-left">
              <button class="btn-back" @click="goBack" title="返回" aria-label="返回">
                <svg viewBox="0 0 1024 1024" width="22" height="22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M515.582162 1023.994371A516.343116 516.343116 0 0 1 204.957513 921.646875a502.014467 502.014467 0 0 1-113.60572-122.816995A486.662342 486.662342 0 0 1 20.73202 642.238212a511.737479 511.737479 0 0 1 990.723759-259.962639 40.938998 40.938998 0 0 1-3.582162 29.169036 36.333361 36.333361 0 0 1-23.539924 17.399074 36.845098 36.845098 0 0 1-29.169036-3.582162 38.892048 38.892048 0 0 1-18.42255-23.539924 436.000332 436.000332 0 0 0-420.13647-324.953299 446.235081 446.235081 0 0 0-111.047033 14.328649 434.976857 434.976857 0 1 0 538.859565 497.40883 37.868573 37.868573 0 0 1 37.356836-32.239462h6.652588a39.915523 39.915523 0 0 1 25.075136 15.863862 38.380311 38.380311 0 0 1 6.14085 28.657299 511.737479 511.737479 0 0 1-374.591835 405.296083 460.563731 460.563731 0 0 1-129.469582 17.910812z" fill="currentColor"></path>
                  <path d="M512 775.801694a35.821624 35.821624 0 0 1-27.122086-11.769962l-225.164491-224.652753a38.892048 38.892048 0 0 1 0-54.244173l225.164491-224.652753a39.915523 39.915523 0 0 1 27.122086-11.769962 37.868573 37.868573 0 0 1 27.122086 11.769962 39.915523 39.915523 0 0 1 11.769962 27.122086 35.821624 35.821624 0 0 1-11.769962 27.122086l-158.638618 158.638619h358.216235a38.892048 38.892048 0 1 1 0 77.272359h-358.216235l159.150356 159.150356a38.892048 38.892048 0 0 1 11.769962 27.122086 37.868573 37.868573 0 0 1-11.769962 27.122087 36.845098 36.845098 0 0 1-27.633824 11.769962z" fill="currentColor"></path>
                </svg>
              </button>
              <h2 class="editor-title">{{ cfg.name || skillId }}</h2>
              <span v-if="db?.version" class="version-chip">v{{ db.version }}</span>
              <span v-if="isTeamSkill && !canEdit" class="readonly-badge">团队仓库只读</span>
              <span v-else-if="!isTeamSkill && db" class="personal-badge">个人 Skill</span>
            </div>
            <div class="toolbar-right">
              <button
                v-if="isTeamSkill && isTeamMember && cfg && !editing"
                class="btn tool-btn publish"
                :disabled="publishingMarket"
                title="发布到 SKILL 市场"
                @click="handlePublishToMarket"
              >{{ publishingMarket ? '发布中…' : '发布到市场' }}</button>
              <template v-if="canEdit && cfg">
                <template v-if="!editing">
                  <button class="btn tool-btn delete" @click="askDeleteSkill">删除</button>
                  <button class="btn tool-btn edit" @click="startEdit">编辑</button>
                </template>
                <template v-else>
                  <button class="btn tool-btn" :disabled="saving" @click="cancelEdit">取消</button>
                  <button class="btn tool-btn save" :disabled="saving" @click="save">
                    {{ saving ? '保存中...' : '保存' }}
                  </button>
                </template>
              </template>
            </div>
          </div>

          <!-- Body: 左侧圆角卡片导航 + 右侧无底色正文 -->
          <div class="editor-body">
            <aside ref="tabSideRef" class="tab-side">
              <span class="tab-slider" :class="{ ready: tabSliderReady }" :style="tabSliderStyle"></span>
              <button class="tab-side-item" :class="{ active: activeTab === 'basic' }" @click="activeTab = 'basic'">基本信息</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'intro' }" @click="activeTab = 'intro'">介绍</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'instructions' }" @click="activeTab = 'instructions'">SKILL 指令</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'resources' }" @click="activeTab = 'resources'">资源</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'metadata' }" @click="activeTab = 'metadata'">元数据</button>
              <button v-if="isTeamSkill || devMock" class="tab-side-item" :class="{ active: activeTab === 'versions' }" @click="activeTab = 'versions'">版本</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'platform' }" @click="activeTab = 'platform'" title="查看各平台 Skill 结构">平台结构</button>
            </aside>

            <div class="tab-content">
              <transition-group
                tag="div"
                class="tab-pane-group"
                :class="{ animating: paneAnimating }"
                :name="paneTransition"
                @after-enter="paneTransitionEnd"
                @after-leave="paneTransitionEnd"
                @enter-cancelled="paneTransitionEnd"
              >
              <!-- Basic -->
              <section v-if="activeTab === 'basic'" key="basic" class="form-section full-width basic-fill">
                <div class="content-card">
                  <h3 class="card-title">通用信息</h3>
                  <div class="form-row">
                    <label class="label-with-tip">
                      名称
                      <HelpTip text="Skill 唯一标识（ID），创建后不可修改。" :size="14" />
                    </label>
                    <input :value="cfg.name || skillId" disabled class="form-input disabled" />
                  </div>
                  <div class="form-row description-fill">
                    <label class="label-with-tip">
                      描述
                      <HelpTip text="说明 Skill 做什么、何时使用；所有平台共用。" :size="14" />
                    </label>
                    <textarea
                      :value="view.description"
                      :disabled="!editing"
                      class="form-input textarea"
                      rows="8"
                      placeholder="简要描述 Skill 的用途"
                      @input="setDraft('description', ($event.target as HTMLTextAreaElement).value)"
                    ></textarea>
                  </div>
                  <div class="meta-inline">
                    <span class="meta-item">
                      <span class="meta-label">来源</span>
                      <span class="meta-value">{{ cfg._import_meta?.source ?? db?.imported_from ?? 'manual' }}</span>
                    </span>
                    <span class="meta-item">
                      <span class="meta-label">创建</span>
                      <span class="meta-value">{{ timeAgo(db?.created_at) }}</span>
                    </span>
                    <span class="meta-item">
                      <span class="meta-label">更新</span>
                      <span class="meta-value">{{ timeAgo(db?.updated_at) }}</span>
                    </span>
                  </div>
                </div>
              </section>

              <!-- 介绍（存于 config.intro，随 Skill 流转；团队成员编辑态可改/可 AI 辅助） -->
              <section v-if="activeTab === 'intro'" key="intro" class="form-section full-width">
                <SkillIntroPanel
                  :title="view.intro?.title"
                  :author="view.intro?.author"
                  :category="view.intro?.category"
                  :md="view.intro?.md"
                  :editing="editing"
                  :skill-id="skillId"
                  :fallback-title="cfg.name || skillId"
                  @update="(f, v) => setDraftNested('intro', f, v)"
                />
              </section>

              <!-- SKILL Instructions（含策略与依赖） -->
              <section v-if="activeTab === 'instructions'" key="instructions" class="form-section full-width instructions-stack">
                <div class="content-card">
                  <h3 class="card-title">
                    技能正文
                    <HelpTip text="Skill.md，纯 Markdown 格式。编写 Skill 的核心指令与工作流。" :size="17" />
                  </h3>
                  <div class="form-row full">
                    <MarkdownEditor v-if="editing" v-model="draftVibeh" />
                    <div v-else class="instructions-view">
                      <MarkdownView :source="vibeh" />
                    </div>
                  </div>
                </div>

                <div class="row-grid">
                  <div class="content-card">
                    <h3 class="card-title">
                      激活策略
                      <HelpTip text="设为 false 时，Cursor 与 Claude 构建产物会包含 disable-model-invocation: true，Codex 构建产物会包含 allow_implicit_invocation: false；Windsurf 不支持该字段（忽略）。" :size="17" />
                    </h3>
                    <div class="form-row checkbox-row">
                      <label>
                        <input
                          type="checkbox"
                          :checked="view.policy?.auto_invoke ?? true"
                          :disabled="!editing"
                          @change="setDraftNested('policy', 'auto_invoke', ($event.target as HTMLInputElement).checked)"
                        />
                        允许 Agent 自动激活
                      </label>
                    </div>
                  </div>

                  <div class="content-card">
                    <h3 class="card-title">
                      通用依赖
                      <HelpTip text="此处仅展示所有平台通用的 Skill 依赖。MCP 工具依赖等平台特有配置请通过「平台结构」查看和编辑。" :size="17" />
                    </h3>
                    <div class="form-row">
                      <label class="label-with-tip">
                        依赖的 Skills
                        <HelpTip text="对应字段 dependencies.skills，逗号分隔，如 $imagegen, $other-skill" :size="14" />
                      </label>
                      <input
                        :value="(view.dependencies?.skills ?? []).join(', ')"
                        :disabled="!editing"
                        class="form-input"
                        placeholder="$imagegen, $other-skill"
                        @change="setDraftNested('dependencies', 'skills', ($event.target as HTMLInputElement).value.split(',').map((s: string) => s.trim()).filter(Boolean))"
                      />
                    </div>
                  </div>
                </div>
              </section>

              <!-- Resources -->
              <section v-if="activeTab === 'resources'" key="resources" class="form-section full-width">
                <h3 class="card-title">
                  资源声明
                  <HelpTip text="以文件夹形式展开 scripts / references / assets；点击文件可打开查看云端真实内容。" :size="17" />
                </h3>
                <template v-if="editing && draft">
                  <div
                    v-for="kind in (['scripts', 'references', 'assets'] as const)"
                    :key="kind"
                    class="form-row"
                  >
                    <label>{{ kind }}</label>
                    <textarea
                      class="form-input code-area"
                      rows="6"
                      spellcheck="false"
                      :value="JSON.stringify(draft.resources?.[kind] ?? [], null, 2)"
                      @change="onResourceEdit(kind, ($event.target as HTMLTextAreaElement).value)"
                    ></textarea>
                  </div>
                </template>
                <ResourceFilesPanel
                  v-else
                  :skill-id="skillId"
                  :resources="cfg.resources"
                  readonly
                />
              </section>

              <!-- Metadata -->
              <section v-if="activeTab === 'metadata'" key="metadata" class="form-section">
                <div class="content-card">
                  <h3 class="card-title">
                    通用元数据
                    <HelpTip text="平台特有的元数据（如 Cursor 的 surfaces 限定）请通过「平台结构」查看。" :size="17" />
                  </h3>
                  <div class="row-grid">
                    <div class="form-row">
                      <label class="label-with-tip">
                        版本
                        <HelpTip text="对应字段 metadata.version" :size="14" />
                      </label>
                      <input
                        :value="view.metadata?.version ?? db?.version ?? '1.0.0'"
                        :disabled="!editing"
                        class="form-input"
                        @input="setDraftNested('metadata', 'version', ($event.target as HTMLInputElement).value)"
                      />
                    </div>
                    <div class="form-row">
                      <label class="label-with-tip">
                        作者
                        <HelpTip text="对应字段 metadata.author" :size="14" />
                      </label>
                      <input
                        :value="view.metadata?.author ?? ''"
                        :disabled="!editing"
                        class="form-input"
                        placeholder="your-name"
                        @input="setDraftNested('metadata', 'author', ($event.target as HTMLInputElement).value)"
                      />
                    </div>
                    <div class="form-row">
                      <label class="label-with-tip">
                        许可证
                        <HelpTip text="对应字段 metadata.license" :size="14" />
                      </label>
                      <input
                        :value="view.metadata?.license ?? ''"
                        :disabled="!editing"
                        class="form-input"
                        placeholder="MIT"
                        @input="setDraftNested('metadata', 'license', ($event.target as HTMLInputElement).value)"
                      />
                    </div>
                    <div class="form-row">
                      <label class="label-with-tip">
                        标签
                        <HelpTip text="对应字段 metadata.tags，逗号分隔" :size="14" />
                      </label>
                      <input
                        :value="(view.metadata?.tags ?? []).join(', ')"
                        :disabled="!editing"
                        class="form-input"
                        placeholder="coding, review"
                        @change="setDraftNested('metadata', 'tags', ($event.target as HTMLInputElement).value.split(',').map((t: string) => t.trim()).filter(Boolean))"
                      />
                    </div>
                  </div>
                </div>
              </section>

              <!-- Versions -->
              <section v-if="activeTab === 'versions'" key="versions" class="form-section full-width">
                <div class="ver-head">
                  <h3 class="card-title ver-card-title">
                    版本历史
                    <HelpTip text="每次推送到团队或团队仓库网页编辑保存时，可选择「更新版本序列号」生成一条版本快照；以下为该 Skill 的全部版本（按序列号倒序）。" :size="17" />
                    <span v-if="devMock" class="dev-mock-chip" title="开发者模式：当前为模拟数据（?mock=1 开启 / ?mock=0 关闭）">模拟数据</span>
                  </h3>
                  <button
                    class="ver-refresh-btn"
                    :class="{ spinning: versionsLoading }"
                    :disabled="versionsLoading"
                    title="刷新"
                    aria-label="刷新"
                    @click="loadVersions"
                  >
                    <svg viewBox="0 0 1024 1024" width="22" height="22" version="1.1" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                      <path d="M958.681412 457.499032c-6.170072-50.632177-20.854483-99.563886-43.643361-145.434552-45.779694-92.144205-122.249797-166.333021-215.325711-208.898719-20.083724-9.18513-43.810309-0.349891-52.995439 19.734833-9.18413 20.082724-0.349891 43.810309 19.733833 52.996438 159.26323 72.834239 245.755201 249.640987 205.658732 420.410622-30.735395 130.876101-129.201624 233.321087-256.187941 270.333521l-0.262918-70.800875-196.843487 114.650172 197.690222 113.176632-0.275914-74.43274c75.398438-17.911403 144.809747-54.929834 202.084849-108.039237 65.597501-60.827991 111.122274-139.186504 131.651859-226.606186 12.170197-51.828803 15.10328-104.683286 8.715276-157.089909zM408.299406-0.001l0.271915 74.43374c-75.404436 17.911403-144.820744 54.931834-202.099843 108.046235-65.6005 60.83099-111.124274 139.191503-131.651859 226.616183-7.987504 34.034364-11.994252 68.507591-11.994252 103.010809 0 17.994377 1.090659 35.996751 3.271978 53.946142 6.152077 50.59119 20.803499 99.48891 43.545392 145.333583 45.678725 92.080225 122.012871 166.270041 214.936832 208.900718 20.071728 9.209122 43.810309 0.401874 53.018432-19.670852 9.210122-20.076726 0.400875-43.810309-19.671853-53.019432-158.963324-72.92821-245.278351-249.658982-205.24886-420.22368 30.732396-130.883099 129.201624-233.333083 256.195939-270.345517l0.259919 70.801874 196.850484-114.640174L408.299406-0.001z" fill="currentColor"></path>
                    </svg>
                  </button>
                </div>

                <div v-if="versionsLoading && !versions.length" class="state-box">
                  <span class="spinner" /> 加载中...
                </div>
                <div v-else-if="!versions.length" class="state-box">
                  暂无版本记录。推送或保存时选择「更新版本序列号」即可创建第一个版本。
                </div>

                <ul v-else class="ver-list">
                  <li v-for="v in versions" :key="v.id" class="ver-item">
                    <div class="ver-row">
                      <span class="ver-seq">v{{ v.seq }}</span>
                      <span v-if="v.label" class="ver-label">{{ v.label }}</span>
                      <span :class="['ver-source', v.source]">{{ sourceLabel(v.source) }}</span>
                      <span v-if="v.resource_count" class="ver-res-chip">{{ v.resource_count }} 个资源文件</span>
                      <span class="ver-meta">{{ v.created_by_name || v.created_by || '—' }} · {{ timeAgo(v.created_at) }}</span>
                      <span class="ver-actions">
                        <button
                          v-if="v.change_items && v.change_items.length"
                          type="button"
                          class="ver-changes-btn"
                          @click="openChanges(v)"
                        >
                          改动明细（{{ v.change_items.length }}）
                        </button>
                        <button class="btn-xs" :disabled="viewLoading" @click="viewVersion(v)">查看版本</button>
                        <button
                          v-if="canEdit || devMock"
                          class="btn-xs danger"
                          :disabled="restoringId === v.id"
                          @click="restore(v)"
                        >
                          {{ restoringId === v.id ? '回滚中...' : '回滚' }}
                        </button>
                      </span>
                    </div>
                    <div v-if="v.change_summary" class="ver-summary">{{ v.change_summary }}</div>
                  </li>
                </ul>
              </section>

              <!-- Platform Structure（内嵌，与个人 Skill 编辑器一致；只读 Skill 时禁用编辑） -->
              <section v-if="activeTab === 'platform'" key="platform" class="form-section full-width">
                <div v-if="skillStore.currentLoading" class="state-box">
                  <span class="spinner" /> 加载中...
                </div>
                <template v-else>
                  <div :class="['platform-embed', { 'platform-readonly': !canEdit }]">
                    <PlatformStructurePanel />
                  </div>
                  <div v-if="canEdit && skillStore.dirty" class="platform-save-bar">
                    <span class="platform-save-hint">平台结构有未保存的改动</span>
                    <button class="btn tool-btn save" :disabled="platformSaving" @click="savePlatform">
                      {{ platformSaving ? '保存中...' : '保存平台结构' }}
                    </button>
                  </div>
                </template>
              </section>
              </transition-group>
            </div>
          </div>
        </template>
      </main>
    </div>

    <!-- 版本内容查看弹窗 -->
    <BaseModal
      :model-value="!!viewingVersion"
      :title="viewingVersion ? `版本 v${viewingVersion.seq} 内容快照` : ''"
      :width="820"
      @update:model-value="closeVersionView"
    >
      <template v-if="viewingVersion">
        <p class="ver-modal-sub">
          {{ sourceLabel(viewingVersion.source) }} · {{ viewingVersion.created_by_name }} · {{ timeAgo(viewingVersion.created_at) }}
        </p>
        <div class="field">
          <label>描述 (description)</label>
          <div class="value pre">{{ (viewingVersion.config as any)?.description || '暂无描述' }}</div>
        </div>
        <div class="field">
          <label>VibeSkill.md 正文</label>
          <div class="ver-md">
            <MarkdownView :source="viewingVersion.vibeh_content" placeholder="（空）" />
          </div>
        </div>
        <div class="field">
          <label>资源文件（scripts / references / assets）</label>
          <ul v-if="viewingVersion.resources && viewingVersion.resources.length" class="ver-res-list">
            <li v-for="p in viewingVersion.resources" :key="p">{{ p }}</li>
          </ul>
          <div v-else class="value">无资源文件</div>
        </div>
        <div class="field">
          <label>skill.config.yaml（JSON 快照）</label>
          <pre class="ver-code">{{ JSON.stringify(viewingVersion.config, null, 2) }}</pre>
        </div>
      </template>
      <template v-if="canEdit && viewingVersion" #footer>
        <button
          class="hdr-btn primary"
          :disabled="restoringId === viewingVersion.id"
          @click="restore(viewingVersion); closeVersionView()"
        >
          回滚到此版本
        </button>
      </template>
    </BaseModal>

    <!-- 改动明细弹窗：逐项渲染字段 / 正文 / 资源的具体改动（替代原下拉栏） -->
    <BaseModal
      :model-value="!!changesVersion"
      :title="changesVersion ? `版本 v${changesVersion.seq} 改动明细` : ''"
      :width="820"
      @update:model-value="closeChanges"
    >
      <template v-if="changesVersion">
        <p class="ver-modal-sub">
          {{ sourceLabel(changesVersion.source) }} · {{ changesVersion.created_by_name || changesVersion.created_by || '—' }} · {{ timeAgo(changesVersion.created_at) }}
        </p>
        <p v-if="changesVersion.change_summary" class="changes-summary">{{ changesVersion.change_summary }}</p>
        <div
          v-for="(item, i) in changesVersion.change_items"
          :key="i"
          class="diff-block"
        >
          <!-- 字段改动：行内字符级高亮 -->
          <template v-if="item.kind === 'field'">
            <div class="diff-block-head">{{ item.label || item.path }}</div>
            <div class="diff-code">
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
            </div>
          </template>

          <!-- 正文改动：unified diff 逐行（含 @@ 行号定位） -->
          <template v-else-if="item.kind === 'body'">
            <div class="diff-block-head">
              正文 VibeSkill.md
              <span class="counts">
                <span class="add">+{{ item.added_lines || 0 }}</span>
                <span class="del">-{{ item.removed_lines || 0 }}</span>
              </span>
            </div>
            <div v-if="bodyRows(item).length" class="diff-code">
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
            <p v-else class="diff-trunc">无正文行级差异记录</p>
            <p v-if="item.diff_truncated" class="diff-trunc">差异较长，仅展示前若干行变更</p>
          </template>

          <!-- 资源改动：可点击，叠加弹窗查看文件内容 / diff -->
          <template v-else>
            <button
              type="button"
              class="diff-resource diff-resource-btn"
              :class="item.change"
              @click="openResource(item)"
            >
              <span class="res-verb">{{ resourceVerb(item.change) }}</span>
              <span class="res-path">{{ item.path }}</span>
              <span class="res-view-hint">查看内容 ›</span>
            </button>
          </template>
        </div>
      </template>
    </BaseModal>

    <!-- 资源文件内容/差异弹窗（叠在改动明细弹窗之上） -->
    <BaseModal
      :model-value="!!resourceView"
      :title="resourceView ? resourceView.path : ''"
      :width="820"
      @update:model-value="closeResource"
    >
      <template v-if="resourceView">
        <p class="ver-modal-sub">
          <span class="res-verb" :class="rvChange">{{ resourceVerb(rvChange) }}</span>
          <template v-if="rvData?.prev_seq != null">相对上一版本 v{{ rvData.prev_seq }}</template>
          <template v-else>该版本无可对比的上一版本</template>
        </p>

        <div v-if="resourceView.loading" class="state-box"><span class="spinner" /> 加载中...</div>
        <div v-else-if="resourceView.error" class="state-box err">{{ resourceView.error }}</div>

        <template v-else>
          <!-- 图片资源：直接预览（修改则前后并排） -->
          <template v-if="rvIsImage">
            <div class="res-img-grid" :class="{ dual: rvChange === 'modified' && rvOld && rvNew }">
              <div v-if="rvChange === 'modified' && rvOld" class="res-img-cell">
                <div class="res-img-cap del">旧 (v{{ rvData?.prev_seq }})</div>
                <img v-if="imageDataUrl(rvOld, resourceView.path)" :src="imageDataUrl(rvOld, resourceView.path)" alt="旧版本" />
                <div v-else class="res-empty">无法预览（{{ fmtSize(rvOld.size) }}）</div>
              </div>
              <div v-if="rvChange !== 'removed' && rvNew" class="res-img-cell">
                <div class="res-img-cap add">{{ rvChange === 'modified' ? '新 (v' + rvData?.seq + ')' : '内容' }}</div>
                <img v-if="imageDataUrl(rvNew, resourceView.path)" :src="imageDataUrl(rvNew, resourceView.path)" alt="新版本" />
                <div v-else class="res-empty">无法预览（{{ fmtSize(rvNew.size) }}）</div>
              </div>
              <div v-if="rvChange === 'removed' && rvOld" class="res-img-cell">
                <div class="res-img-cap del">已删除内容</div>
                <img v-if="imageDataUrl(rvOld, resourceView.path)" :src="imageDataUrl(rvOld, resourceView.path)" alt="已删除" />
                <div v-else class="res-empty">无法预览（{{ fmtSize(rvOld.size) }}）</div>
              </div>
            </div>
          </template>

          <!-- 文本「修改」：unified diff -->
          <template v-else-if="rvChange === 'modified' && rvNew && rvOld && !rvNew.is_binary && !rvOld.is_binary">
            <div v-if="rvDiffRows.length" class="diff-code">
              <div
                v-for="(row, k) in rvDiffRows"
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
            <p v-else class="diff-trunc">内容无文本行级差异（可能仅元信息变化）</p>
            <p v-if="rvData?.diff_truncated" class="diff-trunc">差异较长，仅展示前若干行变更</p>
          </template>

          <!-- 文本「新增」：展示新内容；「删除」：展示被删内容 -->
          <template v-else-if="rvChange === 'added' && rvNew && !rvNew.is_binary">
            <pre class="res-code">{{ rvNew.content || '（空文件）' }}</pre>
          </template>
          <template v-else-if="rvChange === 'removed' && rvOld && !rvOld.is_binary">
            <pre class="res-code">{{ rvOld.content || '（空文件）' }}</pre>
          </template>

          <!-- 兜底：二进制 / 超大 / 无快照 -->
          <div v-else class="res-empty">
            <template v-if="(rvNew && rvNew.too_large) || (rvOld && rvOld.too_large)">
              文件过大，暂不支持在线预览（{{ fmtSize((rvNew || rvOld)?.size) }}）。
            </template>
            <template v-else-if="rvNew || rvOld">
              二进制文件，暂不支持文本预览（{{ fmtSize((rvNew || rvOld)?.size) }}）。
            </template>
            <template v-else>
              未找到该文件的内容快照（可能为较早版本未保存资源快照）。
            </template>
          </div>
        </template>
      </template>
    </BaseModal>

    <!-- 保存确认弹窗：是否更新版本序列号（应用内，替代 window.confirm） -->
    <BaseModal v-model="showSaveConfirm" title="保存修改" :width="440">
      <p class="confirm-text">是否同时更新版本序列号？</p>
      <p class="confirm-hint">
        更新版本：本次保存创建一个新版本（序列号 +1，可在「版本」标签查看 / 回滚）。<br />
        仅保存：只保存内容，不创建版本。
      </p>
      <template #footer>
        <button class="btn tool-btn" :disabled="saving" @click="showSaveConfirm = false">取消</button>
        <button class="btn tool-btn" :disabled="saving" @click="doSave(false)">仅保存</button>
        <button class="btn tool-btn save" :disabled="saving" @click="doSave(true)">更新版本并保存</button>
      </template>
    </BaseModal>

    <!-- 删除 Skill 确认弹窗 -->
    <BaseModal
      v-model="showDeleteSkill"
      title="删除 Skill"
      :closable="!deletingSkill"
      :close-on-overlay="!deletingSkill"
    >
      <p class="confirm-text">
        确认删除 Skill「<strong>{{ cfg?.name || skillId }}</strong>」？
      </p>
      <p class="confirm-hint">
        删除后该 Skill 将从{{ isTeamSkill ? '团队仓库' : '个人仓库' }}移除，关联的部署记录与版本快照将一并删除，且不可恢复。
      </p>
      <template #footer>
        <button class="btn tool-btn" :disabled="deletingSkill" @click="showDeleteSkill = false">
          取消
        </button>
        <button class="btn tool-btn delete" :disabled="deletingSkill" @click="confirmDeleteSkill">
          {{ deletingSkill ? '删除中…' : '确认删除' }}
        </button>
      </template>
    </BaseModal>
  </div>
</template>

<style scoped>
/* ===== 布局：与个人 Skill 编辑器（SkillForge）一致 ===== */
.forge-page {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: var(--canvas);
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
}
.forge-main {
  flex: 1;
  min-height: 0;
  width: 100%;
  padding: 1.5rem 1.5rem 2rem;
  box-sizing: border-box;
  display: flex;
  gap: 1.25rem;
}
.editor-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #9ca3af;
  gap: 0.5rem;
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 16px;
}
.empty-icon { font-size: 3rem; opacity: 0.25; }
.btn-back-repo {
  margin-top: 1rem;
  padding: 0.5rem 1rem;
  background: #151717;
  border: none;
  color: #ffffff;
  border-radius: 9px;
  cursor: pointer;
  font-weight: 600;
  font-size: 0.85rem;
  font-family: inherit;
  transition: background 0.15s ease;
}
.btn-back-repo:hover { background: #2d2f2f; }

/* Toolbar（透明，落在画布上） */
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: transparent;
  flex-wrap: wrap;
  gap: 0.5rem;
  flex-shrink: 0;
}
.toolbar-left { display: flex; align-items: center; gap: 0.75rem; margin-left: 0.5rem; }
.toolbar-right { display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap; }

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
  position: relative;
  top: -3px;
}

.editable-badge,
.readonly-badge,
.personal-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  font-size: 0.72rem;
  font-weight: 600;
  padding: 0.3rem 0.7rem;
  border-radius: 999px;
  line-height: 1;
}
.editable-badge::before,
.readonly-badge::before,
.personal-badge::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.editable-badge { color: #4338ca; background: #e0e7ff; }
.editable-badge::before { background: #6366f1; }
.readonly-badge { color: #4338ca; background: #e0e7ff; }
.readonly-badge::before { background: #6366f1; }
.personal-badge { color: #15803d; background: #dcfce7; }
.personal-badge::before { background: #16a34a; }

.version-chip {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  background: #f6f7f8;
  padding: 4px 10px;
  border-radius: 999px;
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

.btn {
  padding: 0.42rem 0.85rem;
  border: 1px solid #e5e7eb;
  border-radius: 7px;
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
  font-family: inherit;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  background: #ffffff;
  color: #6b7280;
}
.btn:hover:not(:disabled) { border-color: #d1d5db; color: #151717; }
.btn:disabled { opacity: 0.5; cursor: not-allowed; }

.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.45rem;
  box-sizing: border-box;
  min-width: 76px;
  height: 36px;
  padding: 0 0.95rem;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  font-size: 0.88rem;
  font-weight: 600;
  line-height: 1;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease,
    box-shadow 0.16s ease, transform 0.1s ease;
}
.tool-btn:hover:not(:disabled) { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(21, 23, 23, 0.1); }
.tool-btn:active:not(:disabled) { transform: translateY(0) scale(0.97); box-shadow: none; }
.tool-btn.edit { background: #151717; border-color: #151717; color: #ffffff; }
.tool-btn.edit:hover:not(:disabled) { background: #2d2f2f; border-color: #2d2f2f; color: #ffffff; }
.tool-btn.save { background: #0284c7; color: #ffffff; border-color: #0284c7; }
.tool-btn.save:hover:not(:disabled) { background: #0369a1; border-color: #0369a1; color: #ffffff; box-shadow: 0 6px 14px rgba(2, 132, 199, 0.18); }
.tool-btn.delete { background: #dc2626; border-color: #dc2626; color: #ffffff; }
.tool-btn.delete:hover:not(:disabled) { background: #b91c1c; border-color: #b91c1c; color: #ffffff; }
.tool-btn.publish { background: #4f46e5; border-color: #4f46e5; color: #ffffff; }
.tool-btn.publish:hover:not(:disabled) { background: #4338ca; border-color: #4338ca; color: #ffffff; box-shadow: 0 6px 14px rgba(79, 70, 229, 0.2); }

.deploy-msg {
  margin-top: 0.75rem;
  padding: 0.5rem 0.85rem;
  font-size: 0.82rem;
  font-weight: 500;
  border-radius: 10px;
}
.deploy-msg.ok { color: #15803d; background: #f0fdf4; border: 1px solid #bbf7d0; }
.deploy-msg.err { color: #dc2626; background: #fef2f2; border: 1px solid #fecaca; }

/* Body：左侧圆角卡片导航 + 右侧无底色正文 */
.editor-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 1.25rem;
  padding-top: 1.25rem;
}
.tab-side {
  position: relative;
  width: 176px;
  min-width: 176px;
  align-self: stretch;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  background: #eef0f3;
  border: 1px solid #ebedf0;
  border-radius: 14px;
  padding: 0.5rem;
}
/* 选中态黑色滑块：随选中标签纵向平滑滑动到对应位置（高度随项目变化）。 */
.tab-slider {
  position: absolute;
  left: 0.5rem;
  right: 0.5rem;
  top: 0;
  height: 0;
  border-radius: 9px;
  background: #151717;
  opacity: 0;
  z-index: 0;
  pointer-events: none;
  will-change: transform, height;
}
.tab-slider.ready {
  transition: transform 0.28s cubic-bezier(0.4, 0, 0.2, 1),
    height 0.28s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.2s ease;
}
.tab-side-item {
  position: relative;
  z-index: 1;
  text-align: left;
  padding: 0.6rem 0.8rem;
  background: transparent;
  border: none;
  border-radius: 9px;
  color: #6b7280;
  font-size: 0.9rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.tab-side-item:hover:not(.active) { background: #e3e6eb; color: #151717; }
/* 选中项：文字转白加粗；黑色底由 .tab-slider 提供（可滑动） */
.tab-side-item.active { color: #ffffff; font-weight: 600; }

/* 平台结构内嵌：只读 Skill（个人 / 非成员）禁用交互 */
.platform-readonly { pointer-events: none; opacity: 0.92; }
.platform-save-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid #ebedf0;
}
.platform-save-hint { font-size: 0.85rem; color: #6b7280; }

.tab-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 0.25rem 0.25rem 1.5rem;
}

/* 正文滑动容器：切换标签时新旧面板同处一格叠放，沿纵向滑入滑出。 */
.tab-pane-group {
  display: grid;
  min-height: 100%;
}
.tab-pane-group > * {
  grid-area: 1 / 1;
  align-self: start;
}
.tab-pane-group > .basic-fill {
  align-self: stretch;
}
/* 仅在切换动画期间裁剪，避免纵向位移溢出滚动区。 */
.tab-pane-group.animating {
  overflow: hidden;
}

.pane-down-enter-active,
.pane-down-leave-active,
.pane-up-enter-active,
.pane-up-leave-active {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.24s ease;
  will-change: transform, opacity;
}
/* 选择更靠下的标签：新内容自下方滑入，旧内容向上滑出 */
.pane-down-enter-from {
  opacity: 0;
  transform: translateY(26px);
}
.pane-down-leave-to {
  opacity: 0;
  transform: translateY(-26px);
}
/* 选择更靠上的标签：新内容自上方滑入，旧内容向下滑出 */
.pane-up-enter-from {
  opacity: 0;
  transform: translateY(-26px);
}
.pane-up-leave-to {
  opacity: 0;
  transform: translateY(26px);
}

.form-section { max-width: 1320px; }
.full-width { max-width: 100%; }

.content-card {
  background: transparent;
  border: none;
  border-radius: 0;
  padding: 0;
  min-width: 0;
}
.basic-fill .content-card {
  height: 100%;
  display: flex;
  flex-direction: column;
}
.description-fill {
  flex: 1;
  min-height: 160px;
  display: flex;
  flex-direction: column;
}
.description-fill .textarea {
  flex: 1;
  min-height: 160px;
}
.card-title {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0 0 1.2rem;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #151717;
}
.instructions-stack { display: flex; flex-direction: column; gap: 1.25rem; }
.label-with-tip { display: inline-flex; align-items: center; gap: 0.3rem; }

.row-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 1.5rem; }

.meta-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 2.5rem;
  margin-top: 1.1rem;
  padding-top: 0.9rem;
  border-top: 1px solid #f3f4f6;
}
.meta-item { display: inline-flex; align-items: center; gap: 0.5rem; }
.meta-label { font-size: 0.78rem; font-weight: 600; color: #9ca3af; flex-shrink: 0; }
.meta-value { font-size: 0.82rem; color: #374151; }

@media (max-width: 960px) {
  .row-grid { grid-template-columns: 1fr; }
}

.form-row { margin-bottom: 1rem; }
.form-row label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 0.35rem;
}
.form-row label.label-with-tip { display: inline-flex; align-items: center; gap: 0.3rem; }

.form-input {
  width: 100%;
  padding: 0.55rem 0.75rem;
  background: #ffffff;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  transition: border-color 0.15s ease, background 0.15s ease;
  box-sizing: border-box;
}
.form-input:focus { outline: none; border-color: #151717; background: #ffffff; }
.form-input::placeholder { color: #b6bcc4; }
.form-input:disabled { color: #374151; background: #f6f7f8; cursor: default; }
.form-input.disabled { color: #9ca3af; background: #f6f7f8; cursor: not-allowed; }
.form-input.textarea { resize: vertical; min-height: 80px; }
.instructions-editor { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.82rem; line-height: 1.6; min-height: 400px; }
.code-area { font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 0.8rem; }

/* 查看态正文：渲染后的 Markdown 落在白色卡片里 */
.instructions-view {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  min-height: 120px;
}
/* 版本弹窗内的正文渲染区，限制高度可滚动 */
.ver-md {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 12px 14px;
  max-height: 360px;
  overflow: auto;
}

.checkbox-row label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.88rem;
  font-weight: 500;
  color: #151717;
  cursor: pointer;
}
.checkbox-row input[type="checkbox"] { width: 16px; height: 16px; accent-color: #151717; }

/* 版本弹窗底部操作按钮 */
.hdr-btn {
  border: 1px solid #e5e7eb;
  background: #ffffff;
  color: #6b7280;
  border-radius: 9px;
  padding: 6px 14px;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.hdr-btn:hover:not(:disabled) { border-color: #d1d5db; color: #151717; }
.hdr-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.hdr-btn.primary { background: #151717; border-color: #151717; color: #ffffff; font-weight: 600; }
.hdr-btn.primary:hover:not(:disabled) { background: #2d2f2f; border-color: #2d2f2f; color: #ffffff; }

.state-box { margin: 32px auto; text-align: center; color: #9ca3af; }
.state-box.err { color: #dc2626; }

.field { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
.field label { font-size: 13px; font-weight: 600; color: #6b7280; }
.value {
  background: #f6f7f8;
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 14px;
  color: #151717;
}
.value.pre { white-space: pre-wrap; line-height: 1.6; }

.spinner {
  display: inline-block;
  width: 1em;
  height: 1em;
  border: 2px solid #e5e7eb;
  border-top-color: #151717;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle;
}
.spinner.lg { width: 2rem; height: 2rem; border-width: 3px; }
@keyframes spin { to { transform: rotate(360deg); } }

/* ===== 加载骨架屏（还原详情页布局：工具栏 + 左导航 + 右正文） ===== */
.detail-skeleton {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.detail-skeleton .editor-body { padding-top: 1.25rem; }

.sk-block {
  border-radius: 8px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}

.sk-back { width: 38px; height: 38px; border-radius: 50%; flex-shrink: 0; }
.sk-title-lg { width: 220px; height: 26px; }
.sk-chip { width: 52px; height: 22px; border-radius: 999px; }
.sk-btn { width: 76px; height: 36px; border-radius: 10px; }

.detail-skeleton .tab-side { gap: 0.4rem; }
.sk-tab { height: 38px; border-radius: 9px; }

.sk-section-title { width: 160px; height: 24px; margin-bottom: 1.2rem; }
.sk-label { width: 84px; height: 14px; margin-bottom: 0.5rem; }
.sk-input { width: 100%; max-width: 1320px; height: 44px; margin-bottom: 1.1rem; }
.sk-textarea { width: 100%; max-width: 1320px; height: 220px; }

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ---- 版本记录 ---- */
.ver-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.ver-card-title { flex: 1; margin: 0; display: inline-flex; align-items: center; gap: 8px; }
.dev-mock-chip {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: #fef3c7;
  color: #b45309;
}
.ver-list { list-style: none; margin: 0; padding: 0; }
.ver-item {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 12px;
  padding: 12px 14px;
  margin-bottom: 10px;
}
.ver-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.ver-seq {
  font-weight: 700;
  font-size: 15px;
  color: #151717;
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
}
.ver-label {
  font-size: 12px;
  color: #4b5563;
  background: #f3f4f6;
  border-radius: 999px;
  padding: 2px 10px;
}
.ver-source {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef2ff;
  color: #4f46e5;
}
.ver-source.restore { background: #fffbeb; color: #b45309; }
.ver-source.web_edit { background: #f0fdf4; color: #15803d; }
.ver-meta { font-size: 12px; color: #9ca3af; }
.ver-res-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: #f6f7f8;
  color: #6b7280;
}
.ver-res-list {
  list-style: none;
  margin: 0;
  padding: 8px 12px;
  background: #f6f7f8;
  border: 1px solid #ebedf0;
  border-radius: 8px;
}
.ver-res-list li {
  font-size: 12px;
  color: #374151;
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  padding: 2px 0;
}
.ver-actions { margin-left: auto; display: flex; align-items: center; gap: 6px; }
/* 卡片右上角操作按钮：统一为纯色按钮（边框与底色同色，遵循 solid-color-buttons 规范）。
   查看=实底浅灰次级，回滚=实底危险红，与项目页 .btn-soft / .btn-danger 口径一致。 */
.btn-xs {
  border: 1px solid #d4d8db;
  background: #d4d8db;
  color: #3b434f;
  border-radius: 7px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.btn-xs:hover:not(:disabled) { background: #c1c7cd; border-color: #c1c7cd; color: #151717; }
.btn-xs:disabled { opacity: 0.5; cursor: not-allowed; }
.btn-xs.danger { background: #dc2626; border-color: #dc2626; color: #ffffff; }
.btn-xs.danger:hover:not(:disabled) { background: #b91c1c; border-color: #b91c1c; color: #ffffff; }

/* 刷新：纯图标按钮（无背景无边框，hover 绕中心转 60°） */
.ver-refresh-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 42px;
  height: 42px;
  flex-shrink: 0;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: #6b7280;
  cursor: pointer;
  transition: color 0.15s ease;
}
.ver-refresh-btn:hover:not(:disabled) { color: #151717; }
.ver-refresh-btn:disabled { cursor: not-allowed; opacity: 0.7; }
.ver-refresh-btn svg {
  transform-origin: 50% 50%;
  transition: transform 0.3s ease;
}
.ver-refresh-btn:hover:not(:disabled) svg,
.ver-refresh-btn.spinning svg { transform: rotate(60deg); }
.ver-summary { margin-top: 8px; font-size: 13px; color: #374151; }
/* 改动明细触发按钮：纯色浅紫文字按钮，点击打开弹窗（替代原下拉展开）。
   现位于版本行右侧操作区（查看版本左侧），与 .btn-xs 同高对齐。 */
.ver-changes-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  border: 1px solid #e0e7ff;
  background: #eef2ff;
  color: #4f46e5;
  border-radius: 8px;
  padding: 4px 12px;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.ver-changes-btn:hover {
  background: #e0e7ff;
  border-color: #c7d2fe;
  color: #4338ca;
}

/* 改动明细弹窗顶部摘要 */
.changes-summary {
  margin: 0 0 14px;
  font-size: 13px;
  color: #374151;
  line-height: 1.5;
}

/* —— 改动明细：具体文件改动位置（与项目动态「详情」一致的 diff 渲染） —— */
.diff-block { margin-bottom: 12px; }
.diff-block:last-child { margin-bottom: 0; }
.diff-block-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: #4b5563;
  margin-bottom: 6px;
  font-weight: 600;
}
.diff-block-head .counts { font-family: 'JetBrains Mono', monospace; font-weight: 400; }
.diff-block-head .counts .add { color: #16a34a; margin-right: 6px; }
.diff-block-head .counts .del { color: #dc2626; }
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
.diff-line .code { flex: 1; padding-right: 8px; }
.diff-line.add { background: rgba(22, 163, 74, 0.08); }
.diff-line.add .ln { color: #16a34a; }
.diff-line.del { background: rgba(220, 38, 38, 0.07); }
.diff-line.del .ln { color: #dc2626; }
.diff-line.hunk { background: #f6f7f8; color: #6b7280; }
.diff-line.context { color: #6b7280; }
.seg-del { background: rgba(220, 38, 38, 0.18); border-radius: 2px; }
.seg-add { background: rgba(22, 163, 74, 0.2); border-radius: 2px; }
.diff-trunc { margin: 6px 0 0; font-size: 12px; color: #9ca3af; }
.diff-resource {
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  color: #4b5563;
}
.res-verb {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 6px;
  margin-right: 8px;
  font-size: 11px;
}
.added .res-verb,
.res-verb.added { background: #f0fdf4; color: #15803d; }
.removed .res-verb,
.res-verb.removed { background: #fef2f2; color: #dc2626; }
.modified .res-verb,
.res-verb.modified { background: #fef3c7; color: #b45309; }

/* 资源条目按钮：整行可点击，hover 提示「查看内容」 */
.diff-resource-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  width: 100%;
  text-align: left;
  border: 1px solid #ebedf0;
  background: #ffffff;
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.diff-resource-btn:hover { background: #f6f7f8; border-color: #d8dbdf; }
.diff-resource-btn .res-path {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.res-view-hint {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  color: #4f46e5;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  opacity: 0;
  transition: opacity 0.15s ease;
}
.diff-resource-btn:hover .res-view-hint { opacity: 1; }

/* 资源文件内容预览（新增/删除时展示纯文本） */
.res-code {
  background: #f6f7f8;
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 12px;
  margin: 0;
  font-size: 12.5px;
  line-height: 1.6;
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #374151;
  overflow: auto;
  max-height: 460px;
  white-space: pre-wrap;
  word-break: break-word;
}

/* 图片资源预览（修改时前后并排） */
.res-img-grid { display: grid; grid-template-columns: 1fr; gap: 14px; }
.res-img-grid.dual { grid-template-columns: 1fr 1fr; }
.res-img-cell {
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 10px;
  background: #f6f7f8;
  text-align: center;
}
.res-img-cell img {
  max-width: 100%;
  max-height: 360px;
  border-radius: 6px;
  background:
    linear-gradient(45deg, #e9ebee 25%, transparent 25%, transparent 75%, #e9ebee 75%) 0 0/16px 16px,
    linear-gradient(45deg, #e9ebee 25%, #ffffff 25%, #ffffff 75%, #e9ebee 75%) 8px 8px/16px 16px;
}
.res-img-cap {
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 8px;
  display: inline-block;
  padding: 2px 8px;
  border-radius: 6px;
}
.res-img-cap.add { background: #f0fdf4; color: #15803d; }
.res-img-cap.del { background: #fef2f2; color: #dc2626; }
.res-empty {
  background: #f6f7f8;
  border: 1px dashed #d8dbdf;
  border-radius: 8px;
  padding: 18px;
  text-align: center;
  font-size: 13px;
  color: #9ca3af;
}

.ver-modal-sub { font-size: 12px; color: #9ca3af; margin: 0 0 12px; }
.ver-code {
  background: #f6f7f8;
  border: 1px solid #ebedf0;
  border-radius: 8px;
  padding: 12px;
  font-size: 12px;
  font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #374151;
  overflow: auto;
  max-height: 360px;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 768px) {
  .forge-page { height: auto; min-height: 100vh; }
  .forge-main { flex-direction: column; padding: 1rem; }
  .editor-body { flex-direction: column; }
  .tab-side {
    width: 100%;
    min-width: 100%;
    position: static;
    flex-direction: row;
    flex-wrap: wrap;
  }
  .toolbar { align-items: flex-start; }
}
</style>
