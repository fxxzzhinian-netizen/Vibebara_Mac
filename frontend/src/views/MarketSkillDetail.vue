<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  getMarketSkillDetail,
  acquireMarketSkill,
  readMarketResourceFile,
  listMarketSkillVersions,
  getMarketSkillVersionDetail,
  readMarketVersionResourceFile,
  updateMarketSkillIntro,
  removeMarketSkill,
  type MarketSkillItem,
  type MarketVersionItem,
} from '@/api/market'
import { useAuthStore } from '@/stores/authStore'
import { toast } from '@/composables/useToast'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { useSlideIndicator } from '@/composables/useSlideIndicator'
import { useDirectionalTransition } from '@/composables/useDirectionalTransition'
import { formatRelativeTime } from '@/utils/relativeTime'
import AppTopNav from '@/components/AppTopNav.vue'
import MarkdownView from '@/components/MarkdownView.vue'
import ResourceFilesPanel from '@/components/ResourceFilesPanel.vue'
import PlatformStructurePanel from '@/components/PlatformStructurePanel.vue'
import SkillIntroPanel from '@/components/SkillIntroPanel.vue'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const marketId = computed(() => route.params.id as string)

const loading = ref(false)
const error = ref('')
const config = ref<Record<string, any>>({})
const vibehContent = ref('')
const listing = ref<MarketSkillItem | null>(null)

const acquiring = ref(false)
const acquired = ref(false)

type TabKey = 'intro' | 'basic' | 'instructions' | 'resources' | 'metadata' | 'platform' | 'versions'
const activeTab = ref<TabKey>('intro')

// 历史版本（前一代版本）
const versions = ref<MarketVersionItem[]>([])
const versionsLoading = ref(false)
const versionsError = ref('')

// 就地查看历史版本：置 viewingVersionId 后，面板内容切换为该版本的归档快照。
const viewingVersionId = ref<string | null>(null)
const viewingVersionSeq = ref<number | null>(null)
const versionDetailLoading = ref(false)
const isViewingVersion = computed(() => !!viewingVersionId.value)
// 缓存当前版本内容，「返回当前版本」无需重新请求。
const currentSnapshot = ref<{
  config: Record<string, any>
  vibeh: string
  listing: MarketSkillItem | null
} | null>(null)

const tabSideRef = ref<HTMLElement | null>(null)
const { style: tabSliderStyle, ready: tabSliderReady } = useSlideIndicator({
  container: tabSideRef,
  activeSelector: '.tab-side-item.active',
  axis: 'y',
  trigger: () => activeTab.value,
})

const {
  name: paneTransition,
  animating: paneAnimating,
  end: paneTransitionEnd,
} = useDirectionalTransition({
  value: () => activeTab.value,
  order: ['intro', 'basic', 'instructions', 'resources', 'metadata', 'platform', 'versions'],
  names: { forward: 'pane-down', backward: 'pane-up' },
})

const cfg = computed(() => config.value || {})
const displayName = computed(
  () => listing.value?.display_name || cfg.value.name || marketId.value,
)
const introTitle = computed(() => listing.value?.intro_title || displayName.value)
const introAuthor = computed(
  () => listing.value?.intro_author || listing.value?.publisher_name || '',
)
const introCategory = computed(() => listing.value?.intro_category || '')
const introMd = computed(() => {
  const md = (listing.value?.intro_md || '').trim()
  if (md) return md
  // 回退：无介绍正文时用简短描述 / 描述兜底
  return listing.value?.short_description || listing.value?.description || cfg.value.description || ''
})

const isMine = computed(
  () => !!listing.value && listing.value.publisher_id === authStore.user?.id,
)
const isReviewer = computed(() => !!authStore.user?.is_reviewer)
// 管理员（审核员）或发布者本人可改介绍 / 删除条目；查看历史版本时不可。
const canManage = computed(() => (isReviewer.value || isMine.value) && !isViewingVersion.value)

// 编辑介绍
const editingIntro = ref(false)
const savingIntro = ref(false)
const removing = ref(false)
const introDraft = ref({ title: '', author: '', category: '', md: '' })

function startEditIntro() {
  introDraft.value = {
    title: listing.value?.intro_title || '',
    author: listing.value?.intro_author || '',
    category: listing.value?.intro_category || '',
    md: listing.value?.intro_md || '',
  }
  editingIntro.value = true
  activeTab.value = 'intro'
}

function cancelEditIntro() {
  editingIntro.value = false
}

function onIntroDraftUpdate(field: 'title' | 'author' | 'category' | 'md', value: string) {
  introDraft.value = { ...introDraft.value, [field]: value }
}

async function saveIntro() {
  if (savingIntro.value || !marketId.value) return
  savingIntro.value = true
  try {
    const res = await updateMarketSkillIntro(marketId.value, {
      intro_title: introDraft.value.title,
      intro_author: introDraft.value.author,
      intro_category: introDraft.value.category,
      intro_md: introDraft.value.md,
    })
    if (res.success && res.skill) {
      listing.value = res.skill
      if (currentSnapshot.value) currentSnapshot.value.listing = res.skill
      editingIntro.value = false
      toast.success('已更新介绍')
    } else {
      toast.error(res.error || '保存失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || '保存失败')
  } finally {
    savingIntro.value = false
  }
}

async function removeSkill() {
  if (removing.value || !marketId.value) return
  const ok = await confirmDialog({
    title: '删除市场 Skill',
    message: `确认从市场删除「${displayName.value}」？该条目及其历史版本将一并移除，不可恢复。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  removing.value = true
  try {
    const res = await removeMarketSkill(marketId.value)
    if (res.success) {
      toast.success('已从市场删除')
      router.push('/market')
    } else {
      toast.error(res.error || '删除失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || '删除失败')
  } finally {
    removing.value = false
  }
}

const metaTags = computed<string[]>(() => {
  const t = listing.value?.tags
  if (Array.isArray(t) && t.length) return t
  const m = cfg.value.metadata?.tags
  return Array.isArray(m) ? m : []
})

const resources = computed(() => cfg.value.resources || null)

// 资源面板的文件读取器：查看历史版本时读归档快照，否则读当前快照。
function marketFileLoader(path: string) {
  if (viewingVersionId.value) {
    return readMarketVersionResourceFile(marketId.value, viewingVersionId.value, path)
  }
  return readMarketResourceFile(marketId.value, path)
}

function timeAgoStatusLabel(s: string): string {
  const meta: Record<string, string> = {
    pending: '审核中',
    approved: '已通过',
    rejected: '已拒绝',
  }
  return meta[s] || s
}

async function load() {
  if (!marketId.value) return
  loading.value = true
  error.value = ''
  acquired.value = false
  viewingVersionId.value = null
  viewingVersionSeq.value = null
  editingIntro.value = false
  try {
    const res = await getMarketSkillDetail(marketId.value)
    if (res.success) {
      config.value = res.config || {}
      vibehContent.value = res.vibeh_content || ''
      listing.value = res.listing
      currentSnapshot.value = {
        config: res.config || {},
        vibeh: res.vibeh_content || '',
        listing: res.listing,
      }
    } else {
      error.value = res.error || '加载失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e?.message || '请求异常'
  } finally {
    loading.value = false
  }
  loadVersions()
}

async function loadVersions() {
  if (!marketId.value) return
  versionsLoading.value = true
  versionsError.value = ''
  try {
    const res = await listMarketSkillVersions(marketId.value)
    if (res.success) versions.value = res.versions
    else versionsError.value = res.error || '加载历史版本失败'
  } catch (e: any) {
    versionsError.value = e?.response?.data?.detail || e?.message || '请求异常'
  } finally {
    versionsLoading.value = false
  }
}

async function viewVersion(v: MarketVersionItem) {
  if (versionDetailLoading.value || viewingVersionId.value === v.id) return
  versionDetailLoading.value = true
  try {
    const res = await getMarketSkillVersionDetail(marketId.value, v.id)
    if (res.success) {
      config.value = res.config || {}
      vibehContent.value = res.vibeh_content || ''
      listing.value = res.listing
      viewingVersionId.value = v.id
      viewingVersionSeq.value = v.seq
      editingIntro.value = false
      activeTab.value = 'intro'
    } else {
      toast.error(res.error || '加载历史版本失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || '加载历史版本失败')
  } finally {
    versionDetailLoading.value = false
  }
}

function backToCurrent() {
  if (currentSnapshot.value) {
    config.value = currentSnapshot.value.config
    vibehContent.value = currentSnapshot.value.vibeh
    listing.value = currentSnapshot.value.listing
    viewingVersionId.value = null
    viewingVersionSeq.value = null
  } else {
    load()
  }
}

async function acquire() {
  if (acquiring.value || acquired.value || !marketId.value) return
  acquiring.value = true
  try {
    const res = await acquireMarketSkill(marketId.value)
    if (res.success) {
      acquired.value = true
      toast.success('已获取到个人仓库')
    } else {
      toast.error(res.error || '获取失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || '获取失败')
  } finally {
    acquiring.value = false
  }
}

function goBack() {
  if (window.history.length > 1) router.back()
  else router.push('/market')
}

function timeAgo(ts: string | null | undefined): string {
  return formatRelativeTime(ts, { emptyText: '—', relativeDayLimit: 30 })
}

onMounted(load)
watch(marketId, () => {
  activeTab.value = 'intro'
  load()
})
</script>

<template>
  <div class="forge-page">
    <AppTopNav />

    <div class="forge-main">
      <main class="editor-main">
        <!-- Loading -->
        <div v-if="loading" class="state-box"><span class="spinner lg" /></div>

        <!-- Error -->
        <div v-else-if="error" class="empty-state">
          <div class="empty-icon">&#9888;</div>
          <p>{{ error }}</p>
          <button class="btn-back-repo" @click="goBack">← 返回市场</button>
        </div>

        <template v-else>
          <!-- Toolbar -->
          <div class="toolbar">
            <div class="toolbar-left">
              <button class="btn-back" @click="goBack" title="返回" aria-label="返回">
                <svg viewBox="0 0 1024 1024" width="22" height="22" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
                  <path d="M512 775.801694a35.821624 35.821624 0 0 1-27.122086-11.769962l-225.164491-224.652753a38.892048 38.892048 0 0 1 0-54.244173l225.164491-224.652753a39.915523 39.915523 0 0 1 27.122086-11.769962 37.868573 37.868573 0 0 1 27.122086 11.769962 39.915523 39.915523 0 0 1 11.769962 27.122086 35.821624 35.821624 0 0 1-11.769962 27.122086l-158.638618 158.638619h358.216235a38.892048 38.892048 0 1 1 0 77.272359h-358.216235l159.150356 159.150356a38.892048 38.892048 0 0 1 11.769962 27.122086 37.868573 37.868573 0 0 1-11.769962 27.122087 36.845098 36.845098 0 0 1-27.633824 11.769962z" fill="currentColor"></path>
                </svg>
              </button>
              <h2 class="editor-title">{{ displayName }}</h2>
              <span v-if="listing?.version" class="version-chip">v{{ listing.version }}</span>
              <span v-if="isViewingVersion" class="hist-chip">前一代 · 第 {{ viewingVersionSeq }} 版</span>
              <span v-if="listing" :class="['src-badge', listing.source_scope]">
                {{ listing.source_scope === 'team' ? '团队' : '个人' }}
              </span>
            </div>
            <div class="toolbar-right">
              <template v-if="isViewingVersion">
                <button class="btn tool-btn back-current" @click="backToCurrent">返回当前版本</button>
              </template>
              <template v-else>
                <button
                  v-if="canManage"
                  class="btn tool-btn delete"
                  :disabled="removing"
                  @click="removeSkill"
                >{{ removing ? '删除中…' : '删除' }}</button>
                <button v-if="isMine" class="btn tool-btn" disabled>我发布的</button>
                <button
                  v-else
                  class="btn tool-btn acquire"
                  :disabled="acquiring || acquired"
                  @click="acquire"
                >
                  {{ acquired ? '已获取' : acquiring ? '获取中…' : '获取到个人仓库' }}
                </button>
              </template>
            </div>
          </div>

          <!-- 查看历史版本提示横幅 -->
          <div v-if="isViewingVersion" class="hist-banner">
            <span class="hist-banner-text">
              正在查看前一代版本（第 {{ viewingVersionSeq }} 版），内容为只读历史快照。
            </span>
            <button class="hist-banner-btn" @click="backToCurrent">返回当前版本</button>
          </div>

          <!-- Body -->
          <div class="editor-body">
            <aside ref="tabSideRef" class="tab-side">
              <span class="tab-slider" :class="{ ready: tabSliderReady }" :style="tabSliderStyle"></span>
              <button class="tab-side-item" :class="{ active: activeTab === 'intro' }" @click="activeTab = 'intro'">介绍</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'basic' }" @click="activeTab = 'basic'">基本信息</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'instructions' }" @click="activeTab = 'instructions'">SKILL 指令</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'resources' }" @click="activeTab = 'resources'">资源</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'metadata' }" @click="activeTab = 'metadata'">元数据</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'platform' }" @click="activeTab = 'platform'">平台结构</button>
              <button class="tab-side-item" :class="{ active: activeTab === 'versions' }" @click="activeTab = 'versions'">
                历史版本<span v-if="versions.length" class="tab-badge">{{ versions.length }}</span>
              </button>
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
                <!-- Intro（文章样式；管理员/发布者可编辑） -->
                <section v-if="activeTab === 'intro'" key="intro" class="form-section full-width">
                  <div v-if="canManage" class="intro-actions">
                    <template v-if="editingIntro">
                      <button class="intro-act-btn ghost" :disabled="savingIntro" @click="cancelEditIntro">取消</button>
                      <button class="intro-act-btn save" :disabled="savingIntro" @click="saveIntro">
                        {{ savingIntro ? '保存中…' : '保存介绍' }}
                      </button>
                    </template>
                    <button v-else class="intro-act-btn edit" @click="startEditIntro">编辑介绍</button>
                  </div>

                  <SkillIntroPanel
                    v-if="!editingIntro"
                    :title="introTitle"
                    :author="introAuthor"
                    :category="introCategory"
                    :md="introMd"
                    :fallback-title="displayName"
                    empty-placeholder="暂无介绍"
                  />
                  <SkillIntroPanel
                    v-else
                    editing
                    :ai-assist="false"
                    :title="introDraft.title"
                    :author="introDraft.author"
                    :category="introDraft.category"
                    :md="introDraft.md"
                    :fallback-title="displayName"
                    @update="onIntroDraftUpdate"
                  />
                </section>

                <!-- Basic -->
                <section v-else-if="activeTab === 'basic'" key="basic" class="form-section full-width basic-fill">
                  <div class="content-card">
                    <h3 class="card-title">通用信息</h3>
                    <div class="form-row">
                      <label>名称</label>
                      <input :value="cfg.name || displayName" disabled class="form-input disabled" />
                    </div>
                    <div class="form-row description-fill">
                      <label>描述</label>
                      <textarea
                        :value="cfg.description || listing?.description || ''"
                        disabled
                        class="form-input textarea"
                        rows="8"
                      ></textarea>
                    </div>
                    <div class="meta-inline">
                      <span class="meta-item">
                        <span class="meta-label">发布者</span>
                        <span class="meta-value">{{ listing?.publisher_name || '—' }}</span>
                      </span>
                      <span class="meta-item">
                        <span class="meta-label">来源</span>
                        <span class="meta-value">{{ listing?.source_scope === 'team' ? '团队' : '个人' }}</span>
                      </span>
                      <span class="meta-item">
                        <span class="meta-label">发布于</span>
                        <span class="meta-value">{{ timeAgo(listing?.created_at) }}</span>
                      </span>
                    </div>
                  </div>
                </section>

                <!-- Instructions -->
                <section v-else-if="activeTab === 'instructions'" key="instructions" class="form-section full-width">
                  <h3 class="card-title">技能正文</h3>
                  <div class="instructions-view">
                    <MarkdownView :source="vibehContent" placeholder="（空）" />
                  </div>
                </section>

                <!-- Resources -->
                <section v-else-if="activeTab === 'resources'" key="resources" class="form-section full-width">
                  <h3 class="card-title">资源声明</h3>
                  <ResourceFilesPanel
                    :skill-id="marketId"
                    :resources="resources"
                    :file-loader="marketFileLoader"
                    readonly
                  />
                </section>

                <!-- Metadata -->
                <section v-else-if="activeTab === 'metadata'" key="metadata" class="form-section">
                  <div class="content-card">
                    <h3 class="card-title">通用元数据</h3>
                    <div class="row-grid">
                      <div class="form-row">
                        <label>版本</label>
                        <input :value="cfg.metadata?.version || listing?.version || ''" disabled class="form-input disabled" />
                      </div>
                      <div class="form-row">
                        <label>作者</label>
                        <input :value="cfg.metadata?.author || ''" disabled class="form-input disabled" />
                      </div>
                      <div class="form-row">
                        <label>许可证</label>
                        <input :value="cfg.metadata?.license || ''" disabled class="form-input disabled" />
                      </div>
                      <div class="form-row">
                        <label>标签</label>
                        <input :value="metaTags.join(', ')" disabled class="form-input disabled" />
                      </div>
                    </div>
                  </div>
                </section>

                <!-- Platform structure（只读快照） -->
                <section v-else-if="activeTab === 'platform'" key="platform" class="form-section full-width">
                  <div class="platform-embed platform-readonly">
                    <PlatformStructurePanel :config-source="cfg" readonly />
                  </div>
                </section>

                <!-- 历史版本（前一代版本） -->
                <section v-else-if="activeTab === 'versions'" key="versions" class="form-section full-width">
                  <h3 class="card-title">历史版本</h3>
                  <p class="hist-hint">每次重新发布会把上一版内容归档为前一代版本，可点击查看其归档快照。</p>

                  <div v-if="versionsLoading" class="hist-state"><span class="spinner" /> 加载中…</div>
                  <div v-else-if="versionsError" class="hist-state hist-err">{{ versionsError }}</div>
                  <div v-else-if="!versions.length" class="hist-empty">暂无历史版本，当前为初版。</div>
                  <ul v-else class="hist-list">
                    <li
                      v-for="v in versions"
                      :key="v.id"
                      class="hist-row"
                      :class="{ active: viewingVersionId === v.id }"
                    >
                      <div class="hist-row-main">
                        <span class="hist-seq">第 {{ v.seq }} 版</span>
                        <span class="hist-ver">v{{ v.version }}</span>
                        <span :class="['hist-status', v.status]">{{ timeAgoStatusLabel(v.status) }}</span>
                      </div>
                      <div class="hist-row-meta">
                        <span class="hist-time">归档于 {{ timeAgo(v.created_at) }}</span>
                      </div>
                      <button
                        class="hist-view-btn"
                        :disabled="versionDetailLoading || viewingVersionId === v.id"
                        @click="viewVersion(v)"
                      >
                        {{ viewingVersionId === v.id ? '查看中' : '查看' }}
                      </button>
                    </li>
                  </ul>
                </section>
              </transition-group>
            </div>
          </div>
        </template>
      </main>
    </div>
  </div>
</template>

<style scoped>
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
}
.btn-back-repo:hover { background: #2d2f2f; }

/* Toolbar */
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
.toolbar-right { display: flex; align-items: center; gap: 0.5rem; }

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
  transition: background 0.18s ease, color 0.18s ease, transform 0.12s ease;
}
.btn-back:hover { background: #f0f1f2; color: #151717; }
.btn-back:active { transform: scale(0.86); }

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

.version-chip {
  font-size: 12px;
  font-weight: 600;
  color: #6b7280;
  background: #f6f7f8;
  padding: 4px 10px;
  border-radius: 999px;
}
.src-badge {
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 0.18rem 0.6rem;
}
.src-badge.personal { color: #15803d; background: #f0fdf4; }
.src-badge.team { color: #4f46e5; background: #eef2ff; }

.hist-chip {
  font-size: 12px;
  font-weight: 600;
  color: #b45309;
  background: #fffbeb;
  padding: 4px 10px;
  border-radius: 999px;
}

/* 查看历史版本横幅 */
.hist-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin: 0.75rem 0.5rem 0;
  padding: 0.6rem 1rem;
  border: 1px solid #fde68a;
  background: #fffbeb;
  border-radius: 10px;
}
.hist-banner-text { font-size: 0.85rem; color: #92400e; }
.hist-banner-btn {
  flex-shrink: 0;
  padding: 0.35rem 0.85rem;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  background: #ffffff;
  color: #b45309;
  font-size: 0.82rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease;
}
.hist-banner-btn:hover { background: #fef3c7; }

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
.btn:disabled { opacity: 0.55; cursor: not-allowed; }
.tool-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  min-width: 96px;
  height: 36px;
  padding: 0 1rem;
  border-radius: 10px;
  font-size: 0.88rem;
  font-weight: 600;
}
.tool-btn.acquire { background: #151717; border-color: #151717; color: #ffffff; }
.tool-btn.acquire:hover:not(:disabled) { background: #2d2f2f; border-color: #2d2f2f; }
.tool-btn.back-current { background: #ffffff; border-color: #e5e7eb; color: #374151; }
.tool-btn.back-current:hover:not(:disabled) { border-color: #d1d5db; color: #151717; }
.tool-btn.delete { background: #ffffff; border-color: #e5e7eb; color: #dc2626; }
.tool-btn.delete:hover:not(:disabled) { border-color: #fca5a5; background: #fef2f2; color: #dc2626; }

/* Body */
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
  height: fit-content;
}
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
.tab-side-item.active { color: #ffffff; font-weight: 600; }
.tab-badge {
  display: inline-block;
  margin-left: 0.4rem;
  min-width: 1.1rem;
  padding: 0 0.35rem;
  font-size: 0.68rem;
  font-weight: 700;
  line-height: 1.35rem;
  text-align: center;
  color: #6b7280;
  background: #eef0f2;
  border-radius: 999px;
}
.tab-side-item.active .tab-badge { color: #151717; background: #ffffff; }

.tab-content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 0.25rem 0.25rem 1.5rem;
}
.tab-pane-group { display: grid; min-height: 100%; }
.tab-pane-group > * { grid-area: 1 / 1; align-self: start; }
.tab-pane-group > .basic-fill { align-self: stretch; }
.tab-pane-group.animating { overflow: hidden; }

.pane-down-enter-active,
.pane-down-leave-active,
.pane-up-enter-active,
.pane-up-leave-active {
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.24s ease;
  will-change: transform, opacity;
}
.pane-down-enter-from { opacity: 0; transform: translateY(26px); }
.pane-down-leave-to { opacity: 0; transform: translateY(-26px); }
.pane-up-enter-from { opacity: 0; transform: translateY(-26px); }
.pane-up-leave-to { opacity: 0; transform: translateY(26px); }

.form-section { max-width: 1320px; }
.full-width { max-width: 100%; }

.content-card { background: transparent; border: none; padding: 0; min-width: 0; }
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
  margin: 0 0 1.2rem;
  font-size: 1.2rem;
  font-weight: 700;
  letter-spacing: -0.01em;
  color: #151717;
}

.row-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 1.5rem; }
@media (max-width: 960px) { .row-grid { grid-template-columns: 1fr; } }

.form-row { margin-bottom: 1rem; }
.form-row label {
  display: block;
  font-size: 0.8rem;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 0.35rem;
}
.form-input {
  width: 100%;
  padding: 0.55rem 0.75rem;
  background: #ffffff;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  box-sizing: border-box;
}
.form-input.textarea { resize: vertical; min-height: 80px; }
.form-input.disabled { color: #374151; background: #f6f7f8; cursor: default; }

.meta-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 0.4rem 2.5rem;
  margin-top: 1.1rem;
  padding-top: 0.9rem;
  border-top: 1px solid #f3f4f6;
}
.meta-item { display: inline-flex; align-items: center; gap: 0.5rem; }
.meta-label { font-size: 0.78rem; font-weight: 600; color: #9ca3af; }
.meta-value { font-size: 0.82rem; color: #374151; }

.instructions-view {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 10px;
  padding: 1rem 1.25rem;
  min-height: 120px;
}

/* —— 介绍文章（图一样式）—— */
.intro-article {
  max-width: 760px;
  margin: 0 auto;
}
.intro-title {
  margin: 0 0 1rem;
  font-size: 1.9rem;
  font-weight: 800;
  line-height: 1.25;
  letter-spacing: -0.02em;
  color: #151717;
}
.intro-byline {
  display: flex;
  align-items: center;
  gap: 0.65rem;
  margin-bottom: 1.6rem;
  padding-bottom: 1.2rem;
  border-bottom: 1px solid #ebedf0;
}
.intro-avatar {
  width: 30px;
  height: 30px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #151717;
  color: #ffffff;
  font-size: 0.85rem;
  font-weight: 600;
}
.intro-author { font-size: 0.92rem; font-weight: 600; color: #374151; }
.intro-cat {
  font-size: 0.72rem;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  border-radius: 999px;
  padding: 0.2rem 0.7rem;
}
.intro-body {
  font-size: 1rem;
  line-height: 1.8;
  color: #2c2f33;
}

/* 介绍编辑操作行 */
.intro-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.5rem;
  margin-bottom: 1rem;
}
.intro-act-btn {
  padding: 0.4rem 0.9rem;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  color: #374151;
  font-size: 0.82rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}
.intro-act-btn:disabled { opacity: 0.55; cursor: default; }
.intro-act-btn.edit:hover:not(:disabled),
.intro-act-btn.ghost:hover:not(:disabled) { border-color: #d1d5db; color: #151717; }
.intro-act-btn.save { background: #151717; border-color: #151717; color: #ffffff; }
.intro-act-btn.save:hover:not(:disabled) { background: #2d2f2f; border-color: #2d2f2f; }

/* 平台结构只读 */
.platform-readonly { pointer-events: none; opacity: 0.92; }

/* —— 历史版本 —— */
.hist-hint {
  margin: -0.6rem 0 1.2rem;
  font-size: 0.85rem;
  color: #9ca3af;
}
.hist-state {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 1.5rem 0;
  font-size: 0.88rem;
  color: #6b7280;
}
.hist-err { color: #dc2626; }
.hist-empty {
  padding: 1.1rem 1.2rem;
  font-size: 0.88rem;
  color: #9ca3af;
  background: #ffffff;
  border: 1px dashed #e5e7eb;
  border-radius: 12px;
}
.hist-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}
.hist-row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.85rem 1.1rem;
  border: 1px solid #ebedf0;
  border-radius: 12px;
  background: #ffffff;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}
.hist-row:hover { border-color: #d1d5db; }
.hist-row.active { border-color: #f59e0b; background: #fffbeb; }
.hist-row-main {
  display: flex;
  align-items: center;
  gap: 0.6rem;
  min-width: 0;
}
.hist-seq { font-size: 0.92rem; font-weight: 700; color: #151717; }
.hist-ver {
  font-size: 0.72rem;
  font-weight: 600;
  color: #6b7280;
  background: #f6f7f8;
  border-radius: 999px;
  padding: 0.12rem 0.55rem;
}
.hist-status {
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 0.12rem 0.5rem;
}
.hist-status.pending { color: #b45309; background: #fffbeb; }
.hist-status.approved { color: #15803d; background: #f0fdf4; }
.hist-status.rejected { color: #dc2626; background: #fef2f2; }
.hist-row-meta { flex: 1; min-width: 0; }
.hist-time {
  font-size: 0.78rem;
  color: #9ca3af;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.hist-view-btn {
  flex-shrink: 0;
  padding: 0.4rem 0.95rem;
  border: 1px solid #151717;
  border-radius: 8px;
  background: #151717;
  color: #ffffff;
  font-size: 0.82rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.hist-view-btn:hover:not(:disabled) { background: #2d2f2f; border-color: #2d2f2f; }
.hist-view-btn:disabled { opacity: 0.55; cursor: default; }

.state-box { flex: 1; display: flex; align-items: center; justify-content: center; }
.spinner {
  display: inline-block;
  width: 1em;
  height: 1em;
  border: 2px solid #e5e7eb;
  border-top-color: #151717;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
.spinner.lg { width: 2rem; height: 2rem; border-width: 3px; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 768px) {
  .forge-page { height: auto; min-height: 100vh; }
  .forge-main { flex-direction: column; padding: 1rem; }
  .editor-body { flex-direction: column; }
  .tab-side { width: 100%; min-width: 100%; flex-direction: row; flex-wrap: wrap; }
}
</style>
