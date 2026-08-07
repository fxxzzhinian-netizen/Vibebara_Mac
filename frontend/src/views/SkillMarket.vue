<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import AppTopNav from '@/components/AppTopNav.vue'
import AppEmptyState from '@/components/AppEmptyState.vue'
import { toast } from '@/composables/useToast'
import { confirmDialog } from '@/composables/useConfirmDialog'
import { promptInput } from '@/composables/useInputDialog'
import {
  listMarket,
  listMine,
  listPending,
  acquireMarketSkill,
  approveMarketSkill,
  rejectMarketSkill,
  removeMarketSkill,
  listPlatformAdmins,
  grantPlatformAdmin,
  revokePlatformAdmin,
  type MarketSkillItem,
  type PlatformAdminItem,
} from '@/api/market'
import emptyImg from '@/img/status/empty.png'

// SKILL 市场：全局页（个人/团队空间共用）。
// 分页：市场（全体）/ 我的发布 / 审核（审核员）/ 管理员（种子用户）。

const authStore = useAuthStore()
const router = useRouter()

type Tab = 'market' | 'mine' | 'admin'
const activeTab = ref<Tab>('market')

// 点击卡片进入只读「SKILL 介绍」详情页。
function openDetail(s: MarketSkillItem) {
  router.push(`/market/${s.id}`)
}

const isReviewer = computed(() => !!authStore.user?.is_reviewer)
const canManageAdmins = computed(() => !!authStore.user?.can_manage_admins)
const currentUserId = computed(() => authStore.user?.id ?? '')

const showAdminSection = computed(() => isReviewer.value || canManageAdmins.value)

const SKELETON = 6
const loading = ref(false)
const error = ref('')

const marketSkills = ref<MarketSkillItem[]>([])
const mineSkills = ref<MarketSkillItem[]>([])
const pendingSkills = ref<MarketSkillItem[]>([])
const admins = ref<PlatformAdminItem[]>([])

// 已获取的市场条目 id（本次会话内置灰按钮，避免重复获取）
const acquiredIds = ref<Set<string>>(new Set())

function skillDesc(s: MarketSkillItem): string {
  return s.short_description || s.description || '暂无描述'
}

const statusMeta: Record<string, { label: string; cls: string }> = {
  pending: { label: '审核中', cls: 'pending' },
  approved: { label: '已通过', cls: 'approved' },
  rejected: { label: '已拒绝', cls: 'rejected' },
}

async function refreshMarket() {
  loading.value = true
  error.value = ''
  try {
    const res = await listMarket()
    if (res.success) marketSkills.value = res.skills
    else error.value = res.error || '获取市场列表失败'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

async function refreshMine() {
  loading.value = true
  error.value = ''
  try {
    const res = await listMine()
    if (res.success) mineSkills.value = res.skills
    else error.value = res.error || '获取我的发布失败'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

async function refreshPending() {
  loading.value = true
  error.value = ''
  try {
    const res = await listPending()
    if (res.success) pendingSkills.value = res.skills
    else error.value = res.error || '获取审核队列失败'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

async function refreshAdmins() {
  loading.value = true
  error.value = ''
  try {
    const res = await listPlatformAdmins()
    if (res.success) admins.value = res.admins
    else error.value = res.error || '获取管理员列表失败'
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

async function refreshAdminWorkspace() {
  loading.value = true
  error.value = ''
  try {
    const [pendingRes, adminsRes] = await Promise.all([
      isReviewer.value ? listPending() : Promise.resolve(null),
      canManageAdmins.value ? listPlatformAdmins() : Promise.resolve(null),
    ])

    if (pendingRes) {
      if (pendingRes.success) pendingSkills.value = pendingRes.skills
      else error.value = pendingRes.error || '获取审核队列失败'
    }
    if (adminsRes) {
      if (adminsRes.success) admins.value = adminsRes.admins
      else if (!error.value) error.value = adminsRes.error || '获取管理员列表失败'
    }
  } catch (e: any) {
    error.value = e?.response?.data?.detail || e.message || '请求异常'
  } finally {
    loading.value = false
  }
}

function loadTab(tab: Tab) {
  if (tab === 'market') return refreshMarket()
  if (tab === 'mine') return refreshMine()
  if (tab === 'admin') return refreshAdminWorkspace()
}

async function acquire(item: MarketSkillItem) {
  if (acquiredIds.value.has(item.id)) return
  try {
    const res = await acquireMarketSkill(item.id)
    if (res.success) {
      acquiredIds.value = new Set(acquiredIds.value).add(item.id)
      toast.success('已获取到个人仓库')
    } else {
      toast.error(res.error || '获取失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '获取失败')
  }
}

async function approve(item: MarketSkillItem) {
  try {
    const res = await approveMarketSkill(item.id)
    if (res.success) {
      toast.success('已通过')
      await refreshPending()
    } else {
      toast.error(res.error || '操作失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '操作失败')
  }
}

async function reject(item: MarketSkillItem) {
  const note = await promptInput({
    title: '拒绝发布',
    message: `拒绝「${item.display_name || item.source_skill_id}」的发布申请，可填写原因（可留空）。`,
    placeholder: '拒绝原因',
    confirmText: '拒绝',
    multiline: true,
  })
  if (note === null) return
  try {
    const res = await rejectMarketSkill(item.id, note)
    if (res.success) {
      toast.success('已拒绝')
      await refreshPending()
    } else {
      toast.error(res.error || '操作失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '操作失败')
  }
}

async function removeFromMarket(item: MarketSkillItem) {
  const ok = await confirmDialog({
    title: '删除市场 Skill',
    message: `确认从市场删除「${item.display_name || item.source_skill_id}」？该条目及其历史版本将一并移除，不可恢复。`,
    confirmText: '删除',
    danger: true,
  })
  if (!ok) return
  try {
    const res = await removeMarketSkill(item.id)
    if (res.success) {
      toast.success('已从市场删除')
      await refreshMarket()
    } else {
      toast.error(res.error || '删除失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '删除失败')
  }
}

async function removeMine(item: MarketSkillItem) {
  const ok = await confirmDialog({
    title: '撤回发布',
    message: `确认从市场撤回「${item.display_name || item.source_skill_id}」？此操作不可恢复。`,
    confirmText: '撤回',
    danger: true,
  })
  if (!ok) return
  try {
    const res = await removeMarketSkill(item.id)
    if (res.success) {
      toast.success('已撤回')
      await refreshMine()
    } else {
      toast.error(res.error || '撤回失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '撤回失败')
  }
}

async function addAdmin() {
  const username = await promptInput({
    title: '添加平台管理员',
    message: '输入要授予平台管理员的用户名。',
    placeholder: '用户名',
    confirmText: '添加',
  })
  if (username === null) return
  const name = username.trim()
  if (!name) return
  try {
    const res = await grantPlatformAdmin(name)
    if (res.success) {
      toast.success('已添加平台管理员')
      await refreshAdmins()
    } else {
      toast.error(res.error || '添加失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '添加失败')
  }
}

async function revokeAdmin(item: PlatformAdminItem) {
  const ok = await confirmDialog({
    title: '移除平台管理员',
    message: `确认移除「${item.display_name || item.username}」的平台管理员权限？`,
    confirmText: '移除',
    danger: true,
  })
  if (!ok) return
  try {
    const res = await revokePlatformAdmin(item.id)
    if (res.success) {
      toast.success('已移除')
      await refreshAdmins()
    } else {
      toast.error(res.error || '移除失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '移除失败')
  }
}

watch(activeTab, (tab) => loadTab(tab))

onMounted(() => {
  loadTab(activeTab.value)
})
</script>

<template>
  <div class="home">
    <AppTopNav />

    <main class="home-main">
      <!-- 一级分区：标题与菜单在同一左侧导航中 -->
      <div class="toolbar">
        <nav class="section-nav" aria-label="SKILL 市场分区">
          <button
            type="button"
            data-label="SKILL 市场"
            :class="['section-nav-item', 'section-nav-title', { active: activeTab === 'market' }]"
            @click="activeTab = 'market'"
          >
            SKILL 市场
          </button>
          <button
            type="button"
            data-label="我的 SKILL"
            :class="['section-nav-item', { active: activeTab === 'mine' }]"
            @click="activeTab = 'mine'"
          >
            我的 SKILL
          </button>
          <button
            v-if="showAdminSection"
            type="button"
            data-label="SKILL 管理员"
            :class="['section-nav-item', { active: activeTab === 'admin' }]"
            @click="activeTab = 'admin'"
          >
            SKILL 管理员
          </button>
        </nav>
      </div>

      <!-- 内容区 -->
      <div class="pane-group">
        <section :key="activeTab" class="pane">
          <!-- 加载骨架 -->
          <div v-if="loading" class="skill-grid">
            <div v-for="i in SKELETON" :key="i" class="skill-card skeleton">
              <div class="sk-line sk-title"></div>
              <div class="sk-line sk-text"></div>
              <div class="sk-line sk-text short"></div>
              <div class="sk-line sk-foot"></div>
            </div>
          </div>

          <!-- 错误态 -->
          <div v-else-if="error" class="error-bar">
            {{ error }}
            <button class="btn-retry" @click="loadTab(activeTab)">重试</button>
          </div>

          <!-- 市场（全体可见，已通过） -->
          <template v-else-if="activeTab === 'market'">
            <div v-if="marketSkills.length" class="skill-grid">
          <div
            v-for="s in marketSkills"
            :key="s.id"
            class="skill-card clickable"
            role="button"
            tabindex="0"
            @click="openDetail(s)"
            @keydown.enter="openDetail(s)"
          >
            <div class="card-head">
              <span class="card-name">{{ s.display_name || s.source_skill_id }}</span>
              <span class="card-version">v{{ s.version }}</span>
            </div>
            <p class="card-desc">{{ skillDesc(s) }}</p>
            <div v-if="s.tags?.length" class="card-tags">
              <span v-for="tag in s.tags.slice(0, 4)" :key="tag" class="tag">{{ tag }}</span>
              <span v-if="s.tags.length > 4" class="tag more">+{{ s.tags.length - 4 }}</span>
            </div>
            <div class="card-foot">
              <div class="foot-meta">
                <span :class="['src-tag', s.source_scope]">{{ s.source_scope === 'team' ? '团队' : '个人' }}</span>
                <span class="publisher">{{ s.publisher_name }}</span>
              </div>
              <div class="foot-actions">
                <button
                  v-if="isReviewer"
                  class="btn-mini danger"
                  @click.stop="removeFromMarket(s)"
                >删除</button>
                <button
                  v-if="s.publisher_id === currentUserId"
                  class="btn-mini ghost"
                  disabled
                  @click.stop
                >我发布的</button>
                <button
                  v-else
                  class="btn-mini primary"
                  :disabled="acquiredIds.has(s.id)"
                  @click.stop="acquire(s)"
                >{{ acquiredIds.has(s.id) ? '已获取' : '获取' }}</button>
              </div>
            </div>
          </div>
        </div>
        <AppEmptyState
          v-else
          :image="emptyImg"
          title="暂无 Skill"
          description="可添加 Skill，开始构建并丰富你的专属技能库"
        />
      </template>

      <!-- 我的发布 -->
      <template v-else-if="activeTab === 'mine'">
        <div v-if="mineSkills.length" class="skill-grid">
          <div
            v-for="s in mineSkills"
            :key="s.id"
            class="skill-card clickable"
            role="button"
            tabindex="0"
            @click="openDetail(s)"
            @keydown.enter="openDetail(s)"
          >
            <div class="card-head">
              <span class="card-name">{{ s.display_name || s.source_skill_id }}</span>
              <span :class="['status-tag', statusMeta[s.status]?.cls]">{{ statusMeta[s.status]?.label || s.status }}</span>
            </div>
            <p class="card-desc">{{ skillDesc(s) }}</p>
            <p v-if="s.status === 'rejected' && s.review_note" class="reject-note">拒绝原因：{{ s.review_note }}</p>
            <div class="card-foot">
              <div class="foot-meta">
                <span :class="['src-tag', s.source_scope]">{{ s.source_scope === 'team' ? '团队' : '个人' }}</span>
                <span class="publisher">v{{ s.version }}</span>
              </div>
              <button class="btn-mini danger" @click.stop="removeMine(s)">撤回</button>
            </div>
          </div>
        </div>
        <AppEmptyState
          v-else
          :image="emptyImg"
          title="暂无 Skill"
          description="发布后的 Skill 将显示在这里"
        />
      </template>

      <!-- SKILL 管理员：审核与管理员设置合并在同一页面 -->
      <template v-else-if="activeTab === 'admin'">
        <section v-if="isReviewer" class="admin-section">
          <div class="admin-section-head">
            <div>
              <h2>待审核</h2>
              <p>共 {{ pendingSkills.length }} 个待审核发布</p>
            </div>
          </div>
          <div v-if="pendingSkills.length" class="skill-grid">
            <div
              v-for="s in pendingSkills"
              :key="s.id"
              class="skill-card clickable"
              role="button"
              tabindex="0"
              @click="openDetail(s)"
              @keydown.enter="openDetail(s)"
            >
              <div class="card-head">
                <span class="card-name">{{ s.display_name || s.source_skill_id }}</span>
                <span class="card-version">v{{ s.version }}</span>
              </div>
              <p class="card-desc">{{ skillDesc(s) }}</p>
              <div v-if="s.tags?.length" class="card-tags">
                <span v-for="tag in s.tags.slice(0, 4)" :key="tag" class="tag">{{ tag }}</span>
              </div>
              <div class="card-foot">
                <div class="foot-meta">
                  <span :class="['src-tag', s.source_scope]">{{ s.source_scope === 'team' ? '团队' : '个人' }}</span>
                  <span class="publisher">{{ s.publisher_name }}</span>
                </div>
                <div class="foot-actions">
                  <button class="btn-mini ghost" @click.stop="reject(s)">拒绝</button>
                  <button class="btn-mini approve" @click.stop="approve(s)">通过</button>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="admin-empty">
            <strong>没有待审核的发布</strong>
            <span>新的发布申请会出现在这里</span>
          </div>
        </section>

        <section v-if="canManageAdmins" class="admin-section">
          <div class="admin-section-head">
            <div>
              <h2>管理员设置</h2>
              <p>共 {{ admins.length }} 位平台管理员</p>
            </div>
            <button class="btn-primary" @click="addAdmin"><span class="plus">+</span> 添加管理员</button>
          </div>
          <div v-if="admins.length" class="admin-list">
            <div v-for="a in admins" :key="a.id" class="admin-row">
              <div class="admin-avatar">{{ (a.display_name || a.username).slice(0, 1).toUpperCase() }}</div>
              <div class="admin-info">
                <div class="admin-name">{{ a.display_name || a.username }}</div>
                <div class="admin-username">@{{ a.username }}</div>
              </div>
              <span v-if="a.is_seed_user" class="seed-tag">种子用户</span>
              <button
                v-else
                class="btn-mini danger"
                @click="revokeAdmin(a)"
              >移除</button>
            </div>
          </div>
          <div v-else class="admin-empty">
            <strong>还没有平台管理员</strong>
            <span>添加管理员后，他们可以审核市场发布</span>
          </div>
        </section>
      </template>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--canvas);
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
}

.home-main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 2rem;
}

/* —— 标题区文字分选 —— */
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 1.75rem;
}

.section-nav {
  display: flex;
  align-items: flex-end;
  gap: 2.25rem;
  height: 2.1rem;
}

.count {
  font-size: 0.82rem;
  color: #9ca3af;
}

.section-nav-item {
  position: relative;
  padding: 0;
  border: none;
  background: transparent;
  color: #8a93a5;
  font-family: inherit;
  font-size: 1.35rem;
  font-weight: 700;
  line-height: 1.2;
  letter-spacing: -0.02em;
  cursor: pointer;
  transition: color 0.18s ease, font-size 0.2s ease;
}

.section-nav-item::before {
  content: attr(data-label);
  display: block;
  height: 0;
  overflow: hidden;
  visibility: hidden;
  white-space: nowrap;
  font-size: 1.75rem;
  font-weight: 700;
  line-height: 1.2;
}

.section-nav-item:hover,
.section-nav-item.active {
  color: #2f3342;
}

.section-nav-item.active {
  font-size: 1.75rem;
  font-weight: 700;
}

.section-nav-title {
  margin-right: 0.35rem;
}

.admin-section + .admin-section {
  margin-top: 3rem;
}

.admin-section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.admin-section-head h2 {
  margin: 0 0 0.25rem;
  color: #2f3342;
  font-size: 1.05rem;
  font-weight: 650;
}

.admin-section-head p {
  margin: 0;
  color: #8a93a5;
  font-size: 0.82rem;
}

.admin-empty {
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
  padding: 1.25rem 1.4rem;
  border-radius: 12px;
  background: #f6f7fa;
  color: #5f6677;
  font-size: 0.86rem;
}

.admin-empty strong {
  color: #2f3342;
  font-weight: 600;
}

.admin-empty span {
  color: #8a93a5;
  font-size: 0.82rem;
}

/* —— 错误态 —— */
.error-bar {
  margin-bottom: 1rem;
  padding: 0.65rem 1rem;
  border-radius: 10px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #dc2626;
  font-size: 0.86rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
}

.btn-retry {
  padding: 0.3rem 0.8rem;
  border: 1px solid #fca5a5;
  border-radius: 7px;
  background: #ffffff;
  color: #dc2626;
  font-size: 0.8rem;
  font-family: inherit;
  cursor: pointer;
  flex-shrink: 0;
}

.btn-retry:hover {
  background: #fef2f2;
}

/* —— 卡片网格 —— */
.skill-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 1.1rem;
  align-items: stretch;
}

.skill-card {
  display: flex;
  flex-direction: column;
  gap: 0.7rem;
  min-height: 180px;
  padding: 1.25rem 1.3rem;
  border: 1px solid #ebedf0;
  border-radius: 16px;
  background: #ffffff;
  transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}

.skill-card:hover {
  border-color: #d1d5db;
  box-shadow: 0 8px 24px rgba(21, 23, 23, 0.07);
  transform: translateY(-2px);
}

.skill-card.clickable {
  cursor: pointer;
}

.skill-card.clickable:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 2px;
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
  min-height: 3.1em;
}

.reject-note {
  margin: 0;
  font-size: 0.78rem;
  color: #dc2626;
  line-height: 1.4;
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
  margin-top: auto;
  padding-top: 0.65rem;
  border-top: 1px solid #f3f4f6;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.foot-meta {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.foot-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
}

.publisher {
  font-size: 0.78rem;
  color: #9ca3af;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.src-tag {
  flex-shrink: 0;
  font-size: 0.7rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 0.12rem 0.5rem;
}

.src-tag.personal {
  color: #15803d;
  background: #f0fdf4;
}

.src-tag.team {
  color: #4f46e5;
  background: #eef2ff;
}

.status-tag {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 600;
  border-radius: 999px;
  padding: 0.15rem 0.55rem;
}

.status-tag.pending {
  color: #b45309;
  background: #fffbeb;
}

.status-tag.approved {
  color: #15803d;
  background: #f0fdf4;
}

.status-tag.rejected {
  color: #dc2626;
  background: #fef2f2;
}

/* —— 迷你按钮（纯色，遵循纯色按钮规范） —— */
.btn-mini {
  flex-shrink: 0;
  padding: 0.35rem 0.85rem;
  border: 1px solid transparent;
  border-radius: 8px;
  font-size: 0.8rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.btn-mini.primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
}

.btn-mini.primary:hover:not(:disabled) {
  background: #2d2f2f;
  border-color: #2d2f2f;
}

.btn-mini.approve {
  background: #16a34a;
  border-color: #16a34a;
  color: #ffffff;
}

.btn-mini.approve:hover:not(:disabled) {
  background: #15803d;
  border-color: #15803d;
}

.btn-mini.danger {
  background: #ffffff;
  border-color: #e5e7eb;
  color: #dc2626;
}

.btn-mini.danger:hover:not(:disabled) {
  border-color: #fca5a5;
  background: #fef2f2;
}

.btn-mini.ghost {
  background: #ffffff;
  border-color: #e5e7eb;
  color: #6b7280;
}

.btn-mini.ghost:hover:not(:disabled) {
  border-color: #d1d5db;
  color: #151717;
}

.btn-mini:disabled {
  opacity: 0.55;
  cursor: default;
}

/* —— 主按钮 —— */
.btn-primary {
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
  transition: background 0.15s ease, transform 0.1s ease;
}

.btn-primary:hover {
  background: #2d2f2f;
}

.btn-primary:active {
  transform: scale(0.98);
}

.plus {
  font-size: 1.05rem;
  line-height: 1;
  font-weight: 500;
}

/* —— 管理员列表 —— */
.admin-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1rem;
}

.admin-list {
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
}

.admin-row {
  display: flex;
  align-items: center;
  gap: 0.85rem;
  padding: 0.85rem 1.1rem;
  border: 1px solid #ebedf0;
  border-radius: 14px;
  background: #ffffff;
}

.admin-avatar {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #151717;
  color: #ffffff;
  font-weight: 600;
  font-size: 0.95rem;
}

.admin-info {
  flex: 1;
  min-width: 0;
}

.admin-name {
  font-size: 0.92rem;
  font-weight: 600;
  color: #151717;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.admin-username {
  font-size: 0.78rem;
  color: #9ca3af;
}

.seed-tag {
  flex-shrink: 0;
  font-size: 0.72rem;
  font-weight: 600;
  color: #4f46e5;
  background: #eef2ff;
  border-radius: 999px;
  padding: 0.2rem 0.65rem;
}

/* —— 骨架屏 —— */
.skill-card.skeleton {
  pointer-events: none;
}

.sk-line {
  border-radius: 6px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
}

.sk-title { height: 18px; width: 55%; }
.sk-text { height: 12px; width: 90%; }
.sk-text.short { width: 65%; }
.sk-foot { height: 14px; width: 40%; margin-top: 0.5rem; }

@keyframes shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

@media (max-width: 768px) {
  .home-main { padding: 1.25rem 1rem; }
  .section-nav { gap: 1rem; flex-wrap: wrap; }
  .section-nav-title { width: 100%; margin-right: 0; }
  .skill-grid { grid-template-columns: 1fr; }
}
</style>
