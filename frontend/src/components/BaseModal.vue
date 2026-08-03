<script lang="ts">
// 模块级弹窗栈：保证嵌套弹窗时，Esc 只关闭最顶层的一个。
let modalUid = 0
let modalZIndex = 1000
const modalStack: number[] = []
</script>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'

/**
 * 全局弹窗外壳：统一遮罩 + 圆角卡片 + 顶部标题栏（含右上角 × 关闭）。
 * 所有弹窗复用本组件，弹窗自身只需通过默认插槽填正文、#footer 插槽放操作按钮。
 * 关闭方式：点击 × / 点击遮罩 / 按 Esc（均触发 update:modelValue=false 与 close 事件）。
 */
const props = withDefaults(
  defineProps<{
    modelValue: boolean
    title?: string
    /** 卡片宽度，数字按 px 处理，字符串原样使用（如 '720px' / '90vw'） */
    width?: number | string
    /** 点击遮罩是否关闭，默认 true */
    closeOnOverlay?: boolean
    /** 是否可关闭：false 时隐藏 ×、禁用遮罩与 Esc 关闭（用于进行中的不可中断弹窗） */
    closable?: boolean
    /** 正文是否可滚动，默认 true；设为 false 时正文 overflow 可见（用于内部有向外弹出的浮层） */
    bodyScroll?: boolean
  }>(),
  {
    title: '',
    width: 420,
    closeOnOverlay: true,
    closable: true,
    bodyScroll: true,
  },
)

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  (e: 'close'): void
}>()

const boxStyle = computed(() => {
  const w = typeof props.width === 'number' ? `${props.width}px` : props.width
  return { width: w }
})
const activeZIndex = ref(1000)
const overlayStyle = computed(() => ({ zIndex: activeZIndex.value }))

function close() {
  if (!props.closable) return
  emit('update:modelValue', false)
  emit('close')
}

function onOverlay() {
  if (props.closeOnOverlay) close()
}

const myId = ++modalUid

function onKeydown(e: KeyboardEvent) {
  // 仅最顶层弹窗响应 Esc，避免嵌套弹窗被一次性全部关闭
  if (e.key === 'Escape' && modalStack[modalStack.length - 1] === myId) close()
}

function popStack() {
  const i = modalStack.indexOf(myId)
  if (i >= 0) modalStack.splice(i, 1)
  if (modalStack.length === 0) modalZIndex = 1000
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      activeZIndex.value = ++modalZIndex
      modalStack.push(myId)
      window.addEventListener('keydown', onKeydown)
    } else {
      popStack()
      window.removeEventListener('keydown', onKeydown)
    }
  },
)

onBeforeUnmount(() => {
  popStack()
  window.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="bm-fade">
      <div v-if="modelValue" class="bm-overlay" :style="overlayStyle" @click.self="onOverlay">
        <div class="bm-box" :style="boxStyle" role="dialog" aria-modal="true">
          <header class="bm-header">
            <h3 class="bm-title">{{ title }}</h3>
            <button v-if="closable" class="bm-close" type="button" @click="close" title="关闭" aria-label="关闭">×</button>
          </header>
          <div class="bm-body" :class="{ 'bm-body-noscroll': !bodyScroll }">
            <slot />
          </div>
          <footer v-if="$slots.footer" class="bm-footer">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.bm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(21, 23, 23, 0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
  box-sizing: border-box;
}

.bm-box {
  background: #ffffff;
  border: 1px solid #ebedf0;
  border-radius: 16px;
  box-shadow: 0 20px 48px rgba(21, 23, 23, 0.16);
  max-width: 92vw;
  max-height: 88vh;
  display: flex;
  flex-direction: column;
  color: #151717;
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
}

.bm-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 20px 22px 0;
  flex-shrink: 0;
}

.bm-title {
  flex: 1;
  margin: 0;
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.01em;
  line-height: 1.4;
}

.bm-close {
  flex-shrink: 0;
  width: 30px;
  height: 30px;
  margin: -4px -6px 0 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: none;
  background: transparent;
  color: #9ca3af;
  font-size: 22px;
  line-height: 1;
  border-radius: 8px;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}
.bm-close:hover { background: #f3f4f6; color: #151717; }

.bm-body {
  padding: 16px 22px 22px;
  overflow-y: auto;
  flex: 1;
  min-height: 0;
}
.bm-body-noscroll {
  overflow: visible;
}

.bm-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 14px 22px 20px;
  flex-shrink: 0;
}

.bm-fade-enter-active,
.bm-fade-leave-active {
  transition: opacity 0.18s ease;
}
.bm-fade-enter-from,
.bm-fade-leave-to {
  opacity: 0;
}
.bm-fade-enter-active .bm-box,
.bm-fade-leave-active .bm-box {
  transition: transform 0.18s ease;
}
.bm-fade-enter-from .bm-box,
.bm-fade-leave-to .bm-box {
  transform: translateY(8px) scale(0.98);
}
</style>
