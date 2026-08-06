<script setup lang="ts">
import { ref, computed, watch, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useSkillStore } from '@/stores/skillStore'
import { useTeamStore } from '@/stores/teamStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import AppTopNav from '@/components/AppTopNav.vue'
import AddSkillModal from '@/components/AddSkillModal.vue'
import type { NativeSkillItem } from '@/api/skillStore'
import { getSkeletonCount, setSkeletonCount } from '@/utils/skeletonCount'
import { formatRelativeTime } from '@/utils/relativeTime'
import { toast } from '@/composables/useToast'
import cursorIcon from '@/img/icon/cursor.svg'
import codexIcon from '@/img/icon/codex.svg'
import windsurfIcon from '@/img/icon/windsurf.svg'
import claudeIcon from '@/img/icon/claudecode.svg'
import kiroIcon from '@/img/icon/kiro.svg'
import traeIcon from '@/img/icon/trae.svg'
import qoderIcon from '@/img/icon/qoder.svg'
import workbuddyIcon from '@/img/icon/workbuddy.svg'
import emptyImg from '@/img/status/empty.png'
import teamEmptyImg from '@/img/status/team_empty.png'

// 主页 = SKILL 仓库：按当前空间（个人/团队）展示 Skill 卡片网格。

const router = useRouter()
const store = useSkillStore()
const teamStore = useTeamStore()
const workspace = useWorkspaceStore()

const addOpen = ref(false)

const isTeamSpace = computed(() => workspace.spaceType === 'team')

const currentTeamName = computed(
  () => teamStore.teams.find((t) => t.id === workspace.activeTeamId)?.name ?? '',
)

const spaceTitle = computed(() =>
  isTeamSpace.value ? currentTeamName.value || '团队空间' : '个人空间',
)

// 空状态插画：个人空间用 empty.png，团队空间用 team_empty.png
const emptyImage = computed(() => (isTeamSpace.value ? teamEmptyImg : emptyImg))

// 团队空间下按选中团队过滤（fetchList('team') 返回用户全部团队的 Skill）
const displaySkills = computed(() => {
  if (!isTeamSpace.value || !workspace.activeTeamId) return store.skills
  return store.skills.filter((s) => s.team_id === workspace.activeTeamId)
})

// 骨架屏：按当前空间缓存上次后端返回的 Skill 个数，进入页面时先渲染等量占位卡片。
const DEFAULT_SKILL_SKELETON = 6
const skeletonKey = computed(() =>
  isTeamSpace.value
    ? `skills:team:${workspace.activeTeamId ?? 'none'}`
    : 'skills:personal',
)
const skeletonCount = ref(DEFAULT_SKILL_SKELETON)

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
  return store.installedStatus(skill) as unknown as Record<string, boolean>
}

async function refresh() {
  // 先按上次缓存的个数显示骨架屏，再拉取真实列表；加载完成后回写最新个数。
  skeletonCount.value = getSkeletonCount(skeletonKey.value, DEFAULT_SKILL_SKELETON)
  await store.fetchList(workspace.scope)
  setSkeletonCount(skeletonKey.value, displaySkills.value.length)
}

function openSkill(skill: NativeSkillItem) {
  if (skill.scope === 'team') {
    router.push(`/skills/${skill.id}`)
  } else {
    // 先选中再进入个人仓库编辑器，进入后直接定位到该 Skill
    void store.selectSkill(skill.id)
    router.push('/skill-forge')
  }
}

function onAddDone(payload: { message: string; skills?: NativeSkillItem[] }) {
  refresh()
  if (payload.message) toast.success(payload.message)
}

function skillDesc(s: NativeSkillItem): string {
  return s.short_description || s.description || '暂无描述'
}

// 空间切换（含切换具体团队）→ 重新拉取列表
watch(
  () => [workspace.spaceType, workspace.activeTeamId],
  () => refresh(),
)

onMounted(() => {
  workspace.init()
  refresh()
})
</script>

<template>
  <div class="home">
    <AppTopNav />

    <main class="home-main">
      <!-- 工具行 -->
      <div class="toolbar">
        <div class="toolbar-titles">
          <h1 class="page-title">SKILL 仓库</h1>
          <span v-if="!store.loading" class="count">共 {{ displaySkills.length }} 个 Skill</span>
        </div>
        <div class="toolbar-actions">
          <button
            class="btn-primary"
            :disabled="isTeamSpace && !workspace.activeTeamId"
            @click="addOpen = true"
          >
            <span class="plus">+</span> 新增 Skill
          </button>
        </div>
      </div>

      <!-- 错误态 -->
      <div v-if="store.error && !store.loading" class="error-bar">
        {{ store.error }}
        <button class="btn-retry" @click="refresh">重试</button>
      </div>

      <!-- 加载骨架（数量取上次后端返回的真实个数） -->
      <div v-if="store.loading && !displaySkills.length" class="skill-grid">
        <div v-for="i in skeletonCount" :key="i" class="skill-card skeleton">
          <div class="sk-line sk-title"></div>
          <div class="sk-line sk-text"></div>
          <div class="sk-line sk-text short"></div>
          <div class="sk-line sk-foot"></div>
        </div>
      </div>

      <!-- 卡片网格 -->
      <div v-else-if="displaySkills.length" class="skill-grid">
        <div
          v-for="skill in displaySkills"
          :key="skill.id"
          class="skill-card"
          @click="openSkill(skill)"
        >
          <div class="card-head">
            <span class="card-name">{{ skill.display_name || skill.name || skill.id }}</span>
            <span class="card-version">v{{ skill.version }}</span>
          </div>
          <p class="card-desc">{{ skillDesc(skill) }}</p>
          <div v-if="skill.tags?.length" class="card-tags">
            <span v-for="tag in skill.tags.slice(0, 4)" :key="tag" class="tag">{{ tag }}</span>
            <span v-if="skill.tags.length > 4" class="tag more">+{{ skill.tags.length - 4 }}</span>
          </div>
          <div class="card-foot">
            <div class="platform-icons">
              <img
                v-for="p in platforms"
                :key="p.key"
                :src="p.icon"
                :alt="p.label"
                :title="`${p.label}${deployedOn(skill)[p.key] ? '：已部署' : '：未部署'}`"
                :class="['platform-icon', { deployed: deployedOn(skill)[p.key] }]"
              />
            </div>
            <span v-if="skill.updated_at" class="card-time">{{ formatRelativeTime(skill.updated_at) }}</span>
          </div>
        </div>
      </div>

      <!-- 空状态 -->
      <div v-else-if="!store.loading" class="empty-state">
        <div class="empty-illu">
          <img :src="emptyImage" alt="" draggable="false" />
        </div>
        <template v-if="isTeamSpace && !teamStore.teams.length">
          <h2>还没有加入任何团队</h2>
          <p>创建或加入一个团队后，即可在团队空间共享 Skill</p>
          <div class="empty-team-actions">
            <button class="btn-primary" @click="teamStore.openCreateModal()">创建团队</button>
            <button class="btn-ghost" @click="teamStore.openJoinModal()">加入团队</button>
          </div>
        </template>
        <template v-else>
          <h2>{{ spaceTitle }}还没有 Skill</h2>
          <p>新建一个 Skill，或从本地文件夹 / 链接导入</p>
          <button class="btn-primary" @click="addOpen = true"><span class="plus">+</span> 新增 Skill</button>
        </template>
      </div>
    </main>

    <AddSkillModal
      v-model="addOpen"
      :scope="workspace.scope"
      :team-id="isTeamSpace ? workspace.activeTeamId : null"
      @done="onAddDone"
    />
  </div>
</template>

<style scoped>
.home {
  min-height: 100vh;
  background: var(--canvas);
  --card-border: #d1d5db;
  --card-border-hover: #151717;
  --card-shadow: 0 1px 3px rgba(47, 51, 66, 0.06);
  --card-shadow-hover: 0 8px 20px rgba(47, 51, 66, 0.1);
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
}

.home-main {
  max-width: 1280px;
  margin: 0 auto;
  padding: 2rem;
}

/* —— 工具行 —— */
.toolbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 1rem;
  margin-bottom: 1.75rem;
}

/* 标题与计数同一行，计数基线对齐贴在标题右下角 */
.toolbar-titles {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
}

.page-title {
  margin: 0;
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: #151717;
}

.space-tag {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  font-size: 0.78rem;
  font-weight: 600;
  padding: 0.2rem 0.65rem;
  border-radius: 999px;
}

.space-tag::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.space-tag.personal {
  color: #15803d;
  background: #f0fdf4;
}

.space-tag.personal::before {
  background: #16a34a;
}

.space-tag.team {
  color: #4f46e5;
  background: #eef2ff;
}

.space-tag.team::before {
  background: #6366f1;
}

.count {
  font-size: 0.82rem;
  color: #9ca3af;
}

.toolbar-actions {
  display: flex;
  align-items: center;
  gap: 0.6rem;
}

/* —— 按钮 —— */
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

.btn-primary:hover:not(:disabled) {
  background: #2d2f2f;
}

.btn-primary:active:not(:disabled) {
  transform: scale(0.98);
}

.btn-primary:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}

.plus {
  font-size: 1.05rem;
  line-height: 1;
  font-weight: 500;
}

.btn-ghost {
  padding: 0.55rem 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  background: #ffffff;
  color: #6b7280;
  font-size: 0.88rem;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: border-color 0.15s ease, color 0.15s ease;
}

.btn-ghost:hover:not(:disabled) {
  border-color: #d1d5db;
  color: #151717;
}

.btn-ghost:disabled {
  opacity: 0.55;
  cursor: default;
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
  /* 未部署：部分去色 + 降透明度，保留 logo 形状与少量本色（避免浅色 logo 如 Trae 消失），
     不再用 brightness(0) 压成纯黑剪影导致失真 */
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

/* —— 骨架屏 —— */
.skill-card.skeleton {
  cursor: default;
  pointer-events: none;
}

.sk-line {
  border-radius: 6px;
  background: linear-gradient(90deg, #f3f4f6 25%, #e9ebee 50%, #f3f4f6 75%);
  background-size: 200% 100%;
  animation: shimmer 1.4s infinite;
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

@keyframes shimmer {
  0% {
    background-position: 200% 0;
  }
  100% {
    background-position: -200% 0;
  }
}

/* —— 空状态 —— */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  padding: 5rem 1rem;
}

.empty-illu {
  /* 插画底部有大片透明留白，用负边距把下方文字拉近 */
  margin-bottom: -3rem;
}

.empty-illu img {
  width: 280px;
  height: auto;
  user-select: none;
  -webkit-user-drag: none;
}

.empty-state h2 {
  margin: 0 0 0.5rem;
  font-size: 1.15rem;
  font-weight: 600;
  color: #151717;
}

.empty-state p {
  margin: 0 0 1.5rem;
  font-size: 0.88rem;
  color: #9ca3af;
}

.empty-team-actions {
  display: flex;
  gap: 0.6rem;
}

@media (max-width: 768px) {
  .home-main {
    padding: 1.25rem 1rem;
  }

  .toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-actions {
    justify-content: flex-end;
  }

  .skill-grid {
    grid-template-columns: 1fr;
  }
}
</style>
