<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { useWorkspaceStore } from '@/stores/workspaceStore'
import { listTools, type ToolInfo, type ToolId } from '@/api/launcher'
import { toast } from '@/composables/useToast'
import AppLoader from '@/components/AppLoader.vue'
import logoUrl from '@/img/logo.png'
import soloIllus from '@/img/card/solo.png'
import teamIllus from '@/img/card/team.png'
import cursorIcon from '@/img/icon/cursor.svg'
import codexIcon from '@/img/icon/codex.svg'
import windsurfIcon from '@/img/icon/windsurf.svg'
import claudeIcon from '@/img/icon/claudecode.svg'
import kiroIcon from '@/img/icon/kiro.svg'
import traeIcon from '@/img/icon/trae.svg'
import qoderIcon from '@/img/icon/qoder.svg'
import workbuddyIcon from '@/img/icon/workbuddy.svg'

type Phase = 'scene' | 'tools'
type DevMode = 'solo' | 'team'
type PlatformKey =
  | 'cursor'
  | 'codex'
  | 'windsurf'
  | 'claude'
  | 'kiro'
  | 'trae'
  | 'qoder'
  | 'workbuddy'

interface PlatformTool {
  key: PlatformKey
  label: string
  icon: string
}

type IconLoadState = 'loading' | 'ready' | 'error'

const router = useRouter()
const auth = useAuthStore()
const workspace = useWorkspaceStore()

const phase = ref<Phase>('scene')
const devMode = ref<DevMode | null>(null)
const selectedTool = ref<PlatformKey | null>(null)
const detecting = ref(false)
const detected = ref<Set<PlatformKey>>(new Set())
const submitting = ref(false)

const PLATFORM_TOOLS: PlatformTool[] = [
  { key: 'cursor', label: 'Cursor', icon: cursorIcon },
  { key: 'codex', label: 'Codex', icon: codexIcon },
  { key: 'windsurf', label: 'Windsurf', icon: windsurfIcon },
  { key: 'claude', label: 'Claude Code', icon: claudeIcon },
  { key: 'kiro', label: 'Kiro', icon: kiroIcon },
  { key: 'trae', label: 'Trae', icon: traeIcon },
  { key: 'qoder', label: 'Qoder', icon: qoderIcon },
  { key: 'workbuddy', label: 'WorkBuddy', icon: workbuddyIcon },
]

const iconLoadStates = ref<Record<PlatformKey, IconLoadState>>(
  Object.fromEntries(
    PLATFORM_TOOLS.map((tool) => [tool.key, 'loading']),
  ) as Record<PlatformKey, IconLoadState>,
)
let iconPreloadPromise: Promise<void> | null = null

function setIconLoadState(key: PlatformKey, state: IconLoadState) {
  iconLoadStates.value[key] = state
}

function preloadToolIcons(): Promise<void> {
  if (iconPreloadPromise) return iconPreloadPromise
  iconPreloadPromise = Promise.all(
    PLATFORM_TOOLS.map(
      (tool) =>
        new Promise<void>((resolve) => {
          const image = new Image()
          image.onload = async () => {
            try {
              await image.decode()
            } catch {
              // onload 已确认资源可用；部分 Chromium 版本可能不支持重复 decode。
            }
            setIconLoadState(tool.key, 'ready')
            resolve()
          }
          image.onerror = () => {
            setIconLoadState(tool.key, 'error')
            resolve()
          }
          image.src = tool.icon
        }),
    ),
  ).then(() => undefined)
  return iconPreloadPromise
}

// 启动器工具 id → 平台 key（codex-cli/app→codex，claude-code/app→claude，其余同名）
function mapToPlatformKey(id: ToolId): PlatformKey | null {
  switch (id) {
    case 'cursor':
      return 'cursor'
    case 'codex-cli':
    case 'codex-app':
      return 'codex'
    case 'windsurf':
      return 'windsurf'
    case 'claude-code':
    case 'claude-app':
      return 'claude'
    case 'kiro':
      return 'kiro'
    case 'trae':
      return 'trae'
    case 'qoder':
      return 'qoder'
    case 'workbuddy':
      return 'workbuddy'
    default:
      return null
  }
}

// 检测到的工具置顶，其余保持原序
const sortedTools = computed<PlatformTool[]>(() => {
  const found = PLATFORM_TOOLS.filter((t) => detected.value.has(t.key))
  const rest = PLATFORM_TOOLS.filter((t) => !detected.value.has(t.key))
  return [...found, ...rest]
})

// 轮播（coverflow）：选中项居中放大、向两侧逐级缩小，固定展示 7 个图标
// （中心 + 左右各 3，对称），窗口外的图标淡出隐藏，左右切换时循环露出其余图标。
const VISIBLE_LEFT = 3
const VISIBLE_RIGHT = 3
const currentIndex = ref(0)
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1280)

function updateViewportWidth() {
  viewportWidth.value = window.innerWidth
}

// 间距向外逐级递减：中心与相邻间距最大，越往外越小
const GAP_FALLOFF = [1, 0.72, 0.5]

// 第 dist 级图标距中心的累积间距倍数（如 dist=3 → 1 + 0.72 + 0.5 = 2.22）
function cumulativeGap(dist: number): number {
  let sum = 0
  for (let k = 0; k < dist; k++) {
    sum += GAP_FALLOFF[Math.min(k, GAP_FALLOFF.length - 1)]
  }
  return sum
}

// 居中项与相邻项的水平间距：随页面宽度自适应，并设上下限
const spacing = computed(() => {
  const usable = Math.max(420, viewportWidth.value - 240)
  return Math.min(200, usable / (2 * cumulativeGap(VISIBLE_RIGHT)))
})

// 某一级图标的缩放（与 itemStyle 保持一致）
function scaleAt(dist: number): number {
  return Math.max(0.5, 1.18 - dist * 0.26)
}

// 箭头贴在该侧最外卡片外侧：卡片中心偏移 + 该卡片半宽 + 间隙
function edgeArrowOffset(dist: number): number {
  const ICON_WRAP = 128
  const half = (ICON_WRAP * scaleAt(dist)) / 2
  return cumulativeGap(dist) * spacing.value + half + 36
}

const leftArrowStyle = computed(() => ({
  left: `calc(50% - ${edgeArrowOffset(VISIBLE_LEFT)}px)`,
}))
const rightArrowStyle = computed(() => ({
  left: `calc(50% + ${edgeArrowOffset(VISIBLE_RIGHT)}px)`,
}))

// 工具数量超过可见槽位（6 个）时，才需要左右切换
const canScroll = computed(
  () => sortedTools.value.length > VISIBLE_LEFT + VISIBLE_RIGHT + 1,
)

// 选中项始终为居中项
watch(
  [currentIndex, sortedTools],
  () => {
    const t = sortedTools.value[currentIndex.value]
    selectedTool.value = t ? t.key : null
  },
  { immediate: true },
)

// 以居中项为基准的环形偏移：归一化到最近的环向距离
function circularOffset(i: number): number {
  const n = sortedTools.value.length
  const half = Math.floor(n / 2)
  let d = i - currentIndex.value
  if (d > half) d -= n
  if (d < -half) d += n
  return d
}

function itemStyle(i: number) {
  const d = circularOffset(i)
  const dist = Math.abs(d)
  // 仅窗口内（中心 + 左右各 3）可见，其余淡出隐藏，避免环形绕回造成重叠错乱
  const inWindow = d >= -VISIBLE_LEFT && d <= VISIBLE_RIGHT
  const scale = Math.max(0.5, 1.18 - dist * 0.26)
  const opacity = inWindow ? Math.max(0.32, 1 - dist * 0.24) : 0
  const tx = Math.sign(d) * cumulativeGap(dist) * spacing.value
  return {
    transform: `translateX(calc(-50% + ${tx}px)) scale(${scale})`,
    opacity: String(opacity),
    zIndex: String(100 - dist),
    pointerEvents: (inWindow ? 'auto' : 'none') as 'auto' | 'none',
  }
}

// 点击非中心项：滑动使其居中（即选中）
function centerIndex(i: number) {
  if (i < 0 || i >= sortedTools.value.length) return
  currentIndex.value = i
}

function prevTool() {
  const n = sortedTools.value.length
  if (n === 0) return
  currentIndex.value = (currentIndex.value - 1 + n) % n
}

function nextTool() {
  const n = sortedTools.value.length
  if (n === 0) return
  currentIndex.value = (currentIndex.value + 1) % n
}

onMounted(() => {
  updateViewportWidth()
  window.addEventListener('resize', updateViewportWidth)
  void preloadToolIcons()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewportWidth)
})

function chooseScene(mode: DevMode) {
  void preloadToolIcons()
  devMode.value = mode
  phase.value = 'tools'
  currentIndex.value = 0
  void runDetection()
}

async function runDetection() {
  detecting.value = true
  // 保证加载动画（卡皮巴拉进度条）至少展示一段时间：检测/失败可能瞬间返回
  // （如本机无后端时 listTools 立刻报错），否则动画一闪而过看不到。
  const minVisible = new Promise((r) => setTimeout(r, 3000))
  try {
    const tools: ToolInfo[] = await listTools()
    const set = new Set<PlatformKey>()
    for (const t of tools) {
      if (!t.available) continue
      const key = mapToPlatformKey(t.id)
      if (key) set.add(key)
    }
    detected.value = set
  } catch (e) {
    // 检测失败不阻断流程，用户仍可手动选择
    detected.value = new Set()
  } finally {
    await minVisible
    detecting.value = false
  }
}

// 底部圆点步骤指示
const STEPS: Phase[] = ['scene', 'tools']

function goStep(s: Phase) {
  // 检测进行中：锁定步骤切换，避免中途离开
  if (detecting.value) return
  if (s === 'scene') {
    phase.value = 'scene'
  } else if (s === 'tools' && devMode.value) {
    phase.value = 'tools'
  }
}

async function finish() {
  if (!devMode.value || !selectedTool.value || submitting.value) return
  submitting.value = true
  const res = await auth.completeOnboarding(devMode.value, selectedTool.value)
  submitting.value = false
  if (res.success) {
    // 新用户首屏统一进入个人仓库：归位个人空间，清掉可能残留的团队空间状态，
    // 避免被带去（可能不存在/非本人）的团队页。需要团队时由空间切换器进入。
    workspace.switchToPersonal()
    router.replace('/')
  } else {
    toast.error(res.error || '保存失败，请重试')
  }
}
</script>

<template>
  <div class="onboarding-page">
    <img class="page-logo" :src="logoUrl" alt="vibebara" draggable="false" />

    <!-- 阶段一：使用场景二选一 -->
    <transition name="slide-fade">
      <div v-if="phase === 'scene'" class="stage scene-stage">
        <div class="stage-head">
          <h1>平常你对 vibe coding 的使用场景更多是？</h1>
          <p>选择最贴近你的方式，我们会据此优化协作体验</p>
        </div>
        <div class="scene-cards">
          <button class="scene-card" type="button" @click="chooseScene('solo')">
            <span class="scene-illus-wrap" aria-hidden="true">
              <img :src="soloIllus" alt="个人独立开发" class="scene-illus" draggable="false" />
            </span>
            <span class="scene-title">个人独立开发使用</span>
          </button>
          <button class="scene-card" type="button" @click="chooseScene('team')">
            <span class="scene-illus-wrap" aria-hidden="true">
              <img :src="teamIllus" alt="团队协同开发" class="scene-illus" draggable="false" />
            </span>
            <span class="scene-title">团队协同开发</span>
          </button>
        </div>
      </div>
    </transition>

    <!-- 阶段二：工具检索与选择 -->
    <transition name="slide-fade">
      <div v-if="phase === 'tools'" class="stage tools-stage">
        <div class="stage-head">
          <h1>选择你最常用的 Vibe Coding 工具</h1>
          <!-- 检测中：副标题用滚动文字；完成后恢复说明文案 -->
          <AppLoader v-if="detecting" text-only prefix="正在检测本机工具" />
          <p v-else>已为你识别本机工具，选择一个作为默认</p>
        </div>

        <!-- 轮播常驻；检测中仅屏蔽交互，图标保持清晰可见 -->
        <div class="tools-body" :class="{ 'is-loading': detecting }">
          <div class="tools-carousel">
          <button
            v-show="canScroll"
            type="button"
            class="carousel-arrow"
            :style="leftArrowStyle"
            aria-label="上一个"
            @click="prevTool"
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>

          <div class="carousel-stage">
            <button
              v-for="(tool, i) in sortedTools"
              :key="tool.key"
              type="button"
              class="carousel-item"
              :class="{ active: i === currentIndex }"
              :style="itemStyle(i)"
              @click="centerIndex(i)"
            >
              <span class="carousel-icon-wrap">
                <span v-if="detected.has(tool.key)" class="tool-check" aria-label="已检测到">
                  <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M20 6L9 17l-5-5" />
                  </svg>
                  <span class="tool-check-tip">已检测到</span>
                </span>
                <span
                  v-if="iconLoadStates[tool.key] === 'loading'"
                  class="tool-icon-placeholder"
                  aria-hidden="true"
                ></span>
                <span
                  v-else-if="iconLoadStates[tool.key] === 'error'"
                  class="tool-icon-fallback"
                  role="img"
                  :aria-label="`${tool.label} 图标加载失败`"
                >
                  {{ tool.label.slice(0, 1).toUpperCase() }}
                </span>
                <img
                  :src="tool.icon"
                  :alt="tool.label"
                  class="tool-icon"
                  :class="{ ready: iconLoadStates[tool.key] === 'ready' }"
                  decoding="async"
                  draggable="false"
                  @load="setIconLoadState(tool.key, 'ready')"
                  @error="setIconLoadState(tool.key, 'error')"
                />
              </span>
              <span class="tool-label">{{ tool.label }}</span>
            </button>
          </div>

          <button
            v-show="canScroll"
            type="button"
            class="carousel-arrow"
            :style="rightArrowStyle"
            aria-label="下一个"
            @click="nextTool"
          >
            <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M9 18l6-6-6-6" />
            </svg>
          </button>
        </div>

        <button
          type="button"
          class="finish-btn"
          :disabled="!selectedTool || submitting"
          @click="finish"
        >
          {{ submitting ? '正在进入…' : '进入工作台' }}
        </button>
        </div>
      </div>
    </transition>

    <!-- 底部圆点步骤指示 -->
    <transition name="fade">
      <div class="step-dots">
        <button
          v-for="(s, i) in STEPS"
          :key="s"
          type="button"
          class="step-dot"
          :class="{ active: phase === s }"
          :disabled="detecting"
          :aria-label="`第 ${i + 1} 步`"
          @click="goStep(s)"
        ></button>
      </div>
    </transition>
  </div>
</template>

<style scoped>
.onboarding-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: flex-start;
  justify-content: center;
  background-color: #ffffff;
  background-size: cover;
  background-position: center;
  background-repeat: no-repeat;
  padding: clamp(72px, 13vh, 150px) 24px 24px;
  box-sizing: border-box;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
    Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  overflow: hidden;
}

.page-logo {
  position: absolute;
  top: 28px;
  left: 32px;
  height: 30px;
  z-index: 5;
}

.stage {
  width: 100%;
  max-width: 920px;
  display: flex;
  flex-direction: column;
  align-items: center;
}

/* 工具步骤：铺满页面宽度；箭头按间距贴在最外侧图标旁 */
.tools-stage {
  max-width: none;
}

.stage-head {
  text-align: center;
  margin-bottom: 46px;
}

.stage-head h1 {
  font-size: 32px;
  font-weight: 650;
  color: #151717;
  margin: 0 0 14px;
}

.stage-head p {
  font-size: 17px;
  color: #6b7280;
  margin: 0;
}

/* 场景卡片 */
.scene-cards {
  display: flex;
  gap: 30px;
  width: 100%;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 28px;
}

.scene-card {
  flex: 1 1 360px;
  max-width: 420px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 40px 48px 44px;
  background: #ffffff;
  border: 2px solid transparent;
  border-radius: 22px;
  cursor: pointer;
  color: #151717;
  transition: transform 0.2s ease, border-color 0.2s ease,
    box-shadow 0.2s ease;
}

.scene-card:hover {
  transform: translateY(-4px);
  border-color: #151717;
  box-shadow: 0 12px 30px rgba(21, 23, 23, 0.1);
}

.scene-illus-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 210px;
  margin-bottom: 8px;
}

.scene-illus {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  user-select: none;
}

.scene-title {
  font-size: 20px;
  font-weight: 600;
}

/* 工具区容器：检测中屏蔽交互/选中，并承载半透明遮罩 */
.tools-body {
  position: relative;
  width: 100%;
  margin-top: -24px;
  transform: scale(1.15);
  transform-origin: top center;
}

.tools-body.is-loading {
  pointer-events: none;
  user-select: none;
}

/* 工具轮播（coverflow）：选中项居中最大、两侧逐级缩小；固定可见 7 个（左右各 3），箭头贴边 */
.tools-carousel {
  position: relative;
  width: 100%;
  margin-top: 32px;
  padding: 0 56px;
  box-sizing: border-box;
}

.carousel-stage {
  position: relative;
  width: 100%;
  height: 220px;
}

.carousel-arrow {
  position: absolute;
  top: 80px;
  transform: translate(-50%, -50%);
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border: none;
  border-radius: 999px;
  background: transparent;
  color: #9ca3af;
  cursor: pointer;
  z-index: 200;
  transition: color 0.2s ease;
}

.carousel-arrow:hover {
  color: #151717;
}

.carousel-item {
  position: absolute;
  top: 18px;
  left: 50%;
  width: 150px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 16px;
  padding: 0;
  border: none;
  background: transparent;
  color: #151717;
  cursor: pointer;
  transform-origin: center 64px;
  transition: transform 0.5s cubic-bezier(0.22, 1, 0.36, 1),
    opacity 0.5s ease;
}

.carousel-icon-wrap {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 128px;
  height: 128px;
  border-radius: 30px;
  background: #f6f7f8;
  transition: background 0.4s ease, box-shadow 0.4s ease;
}

.carousel-item.active .carousel-icon-wrap {
  background: #ffffff;
  box-shadow: 0 16px 38px rgba(21, 23, 23, 0.18);
}

.tool-icon {
  position: absolute;
  width: 70px;
  height: 70px;
  object-fit: contain;
  opacity: 0;
  transition: opacity 0.18s ease;
}

.tool-icon.ready {
  opacity: 1;
}

.tool-icon-placeholder,
.tool-icon-fallback {
  position: absolute;
  width: 58px;
  height: 58px;
  border-radius: 16px;
}

.tool-icon-placeholder {
  background: linear-gradient(90deg, #eceef1 25%, #f7f8f9 50%, #eceef1 75%);
  background-size: 200% 100%;
  animation: icon-shimmer 1.1s ease-in-out infinite;
}

.tool-icon-fallback {
  display: flex;
  align-items: center;
  justify-content: center;
  background: #e5e7eb;
  color: #4b5563;
  font-size: 24px;
  font-weight: 700;
  line-height: 1;
}

@keyframes icon-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.tool-label {
  font-size: 14px;
  font-weight: 550;
  white-space: nowrap;
  transition: font-weight 0.3s ease;
}

.carousel-item.active .tool-label {
  font-weight: 650;
}

/* 已检测到：图标右上角对勾，悬停/触摸弹出说明 */
.tool-check {
  position: absolute;
  top: -7px;
  right: -7px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 999px;
  background: #16a34a;
  color: #ffffff;
  box-shadow: 0 0 0 2.5px #ffffff;
  z-index: 3;
  cursor: help;
}

.tool-check-tip {
  position: absolute;
  bottom: calc(100% + 9px);
  left: 50%;
  transform: translateX(-50%) translateY(3px);
  padding: 5px 10px;
  border-radius: 7px;
  background: #151717;
  color: #ffffff;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
  white-space: nowrap;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.18s ease, transform 0.18s ease;
}

/* 气泡小三角 */
.tool-check-tip::after {
  content: "";
  position: absolute;
  top: 100%;
  left: 50%;
  transform: translateX(-50%);
  border: 5px solid transparent;
  border-top-color: #151717;
}

.tool-check:hover .tool-check-tip,
.tool-check:focus-visible .tool-check-tip {
  opacity: 1;
  transform: translateX(-50%) translateY(0);
}

.err-text {
  margin: 18px 0 0;
  color: #dc2626;
  font-size: 13.5px;
  text-align: center;
}

.finish-btn {
  display: block;
  margin: 60px auto 0;
  min-width: 200px;
  height: 50px;
  padding: 0 28px;
  background: #151717;
  color: #ffffff;
  border: 1.5px solid #151717;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.06em;
  cursor: pointer;
  transition: opacity 0.2s ease;
}

.finish-btn:hover:not(:disabled) {
  opacity: 0.86;
}

.finish-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 底部圆点步骤指示 */
.step-dots {
  position: absolute;
  left: 50%;
  bottom: 40px;
  transform: translateX(-50%);
  display: flex;
  align-items: center;
  gap: 10px;
}

.step-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border: none;
  border-radius: 999px;
  background: #d1d5db;
  cursor: pointer;
  transition: width 0.3s ease, background-color 0.3s ease;
}

.step-dot:hover {
  background: #9ca3af;
}

.step-dot:disabled {
  cursor: not-allowed;
}

.step-dot:disabled:hover {
  background: #d1d5db;
}

.step-dot.active {
  width: 24px;
  background: #151717;
}

.step-dot.active:hover {
  background: #151717;
}

/* 过渡动画 */
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.5s ease;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.slide-fade-enter-active {
  transition: opacity 0.45s ease, transform 0.45s ease;
}
.slide-fade-enter-from {
  opacity: 0;
  transform: translateY(16px);
}

@media (max-width: 640px) {
  .scene-cards {
    flex-direction: column;
    align-items: center;
  }
}
</style>
