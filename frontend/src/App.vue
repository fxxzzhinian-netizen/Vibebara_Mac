<script setup lang="ts">
import { RouterView } from 'vue-router'
import InputDialog from '@/components/InputDialog.vue'
import ConfirmDialog from '@/components/ConfirmDialog.vue'
import ChoiceDialog from '@/components/ChoiceDialog.vue'
import AppToast from '@/components/AppToast.vue'
</script>

<template>
  <div id="app-layout">
    <!-- 路由切页过渡：内容交叉淡入淡出。
         离场页绝对定位与入场页重叠，而顶栏在每个页面中位置/外观一致，
         因此视觉上顶栏保持稳定（白色胶囊仍由 useSlideIndicator 记忆位置平滑滑动），
         只有正文做淡入淡出，消除整页的硬切换。 -->
    <RouterView v-slot="{ Component }">
      <transition name="page">
        <component :is="Component" />
      </transition>
    </RouterView>
    <InputDialog />
    <ConfirmDialog />
    <ChoiceDialog />
    <AppToast />
  </div>
</template>

<style>
:root {
  --primary: #6366f1;
  --primary-hover: #4f46e5;
  --bg: #ffffff;
  /* 工作区统一使用与引导页一致的纯白画布 */
  --canvas-color: #ffffff;
  --canvas: var(--canvas-color);
  --surface: #f6f7f8;
  --surface-hover: #eef0f2;
  --border: #e5e7eb;
  --text: #151717;
  --text-muted: #6b7280;
  --success: #16a34a;
  --warning: #d97706;
  --danger: #dc2626;
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen,
    Ubuntu, sans-serif;
  background-color: var(--canvas-color);
  background: var(--canvas);
  color: var(--text);
  min-height: 100vh;
  /* 仅在视口滚动条出现时增加等宽左内边距，使内容仍以完整视口为中心；
     短页面不预留右侧滚动条槽位，因此不会出现固定留白。 */
  padding-left: calc(100vw - 100%);
}

/* ===== 全局滚动条样式 ===== */
:root {
  --scrollbar-size: 12px;
  --scrollbar-thumb: rgba(99, 102, 241, 0.4);
  --scrollbar-thumb-hover: rgba(99, 102, 241, 0.62);
  --scrollbar-track: transparent;
}

/* Firefox（及不支持 ::-webkit-scrollbar 的引擎）才使用标准属性。
   重要：标准 scrollbar-width / scrollbar-color 一旦为非初始值，Chromium 会按规范
   忽略 ::-webkit-scrollbar 自定义样式（圆头滑块失效、退化为方头细滚动条）。
   因此用 @supports 仅在不支持 webkit 伪元素时启用，确保 Chromium/Electron 走下方圆头样式。 */
@supports not selector(::-webkit-scrollbar) {
  * {
    scrollbar-width: thin;
    scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
  }
}

/* WebKit / Chromium / Edge */
*::-webkit-scrollbar {
  width: var(--scrollbar-size);
  height: var(--scrollbar-size);
}

*::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-radius: 999px;
}

/* 滑块直接用纯色背景 + border-radius 实现圆头：不依赖 background-clip:padding-box，
   避免个别 Chromium/Electron 版本下透明边框+裁剪把两端渲染成方头。 */
*::-webkit-scrollbar-thumb {
  background-color: var(--scrollbar-thumb);
  border-radius: 999px;
  transition: background-color 0.2s ease;
}

*::-webkit-scrollbar-thumb:hover,
*::-webkit-scrollbar-thumb:active {
  background-color: var(--scrollbar-thumb-hover);
}

/* 去掉两端的上/下箭头按钮 */
*::-webkit-scrollbar-button {
  display: none;
  width: 0;
  height: 0;
}

/* 横竖滚动条交汇处透明 */
*::-webkit-scrollbar-corner {
  background: transparent;
}

#app-layout {
  min-height: 100vh;
  /* 作为切页过渡中「离场页」绝对定位的包含块 */
  position: relative;
}

/* ===== 路由切页过渡（交叉淡入淡出） ===== */
.page-enter-active,
.page-leave-active {
  transition: opacity 0.24s ease;
}

/* 离场页脱离文档流并铺满，与入场页重叠，避免上下错位跳动；
   不设 bottom，保留页面自然高度，防止长页面被裁切。 */
.page-leave-active {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
}

.page-enter-from,
.page-leave-to {
  opacity: 0;
}
</style>
