<script setup lang="ts">
import { computed } from 'vue'
import MarkdownView from '@/components/MarkdownView.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'

// 可复用「介绍」面板：查看态为文章样式，编辑态提供标题/分类/作者输入、
// Markdown 正文编辑与「AI 辅助生成」。介绍内容存于 Skill 自身 config.intro。
const props = withDefaults(
  defineProps<{
    title?: string
    author?: string
    category?: string
    md?: string
    editing?: boolean
    skillId?: string
    generating?: boolean
    fallbackTitle?: string
    // 是否提供「AI 辅助生成」（市场条目编辑无对应源 Skill，关闭即可）。
    aiAssist?: boolean
    // 查看态空正文占位文案。
    emptyPlaceholder?: string
  }>(),
  { aiAssist: true, generating: false },
)

const emit = defineEmits<{
  (e: 'update', field: 'title' | 'author' | 'category' | 'md', value: string): void
  (e: 'ai-generate'): void
}>()

const displayTitle = computed(() => (props.title || '').trim() || props.fallbackTitle || '')
const displayAuthor = computed(() => (props.author || '').trim())
const displayCategory = computed(() => (props.category || '').trim())
const authorInitial = computed(() => (displayAuthor.value || '?').slice(0, 1).toUpperCase())

function aiGenerate() {
  if (!props.generating) emit('ai-generate')
}
</script>

<template>
  <!-- 编辑态 -->
  <div v-if="editing" class="intro-edit">
    <div v-if="aiAssist" class="intro-toolbar">
      <button
        type="button"
        class="ai-btn"
        :class="{ generating }"
        :disabled="generating"
        :aria-label="generating ? 'AI 辅助生成中' : 'AI 辅助生成'"
        @click="aiGenerate"
      >
        <span class="ai-layer" aria-hidden="true">
          <span class="ai-layer-sheet"></span>
          <span class="ai-layer-sheet"></span>
          <span class="ai-layer-sheet"></span>
          <span class="ai-layer-sheet"></span>
          <span class="ai-layer-sheet ai-layer-face">
            <span v-if="generating" class="spinner" />
            <svg
              v-else
              class="openai-icon"
              viewBox="0 0 24 24"
              xmlns="http://www.w3.org/2000/svg"
            >
              <path
                d="M22.2819 9.8211a5.9847 5.9847 0 0 0-.5157-4.9108 6.0462 6.0462 0 0 0-6.5098-2.9A6.0651 6.0651 0 0 0 4.9807 4.1818a5.9847 5.9847 0 0 0-3.9977 2.9 6.0462 6.0462 0 0 0 .7427 7.0966 5.98 5.98 0 0 0 .511 4.9107 6.051 6.051 0 0 0 6.5146 2.9001A5.9847 5.9847 0 0 0 13.2599 24a6.0557 6.0557 0 0 0 5.7718-4.2058 5.9894 5.9894 0 0 0 3.9977-2.9001 6.0557 6.0557 0 0 0-.7475-7.0729zm-9.022 12.6081a4.4755 4.4755 0 0 1-2.8764-1.0408l.1419-.0804 4.7783-2.7582a.7948.7948 0 0 0 .3927-.6813v-6.7369l2.02 1.1686a.071.071 0 0 1 .038.052v5.5826a4.504 4.504 0 0 1-4.4945 4.4944zm-9.6607-4.1254a4.4708 4.4708 0 0 1-.5346-3.0137l.142.0852 4.783 2.7582a.7712.7712 0 0 0 .7806 0l5.8428-3.3685v2.3324a.0804.0804 0 0 1-.0332.0615L9.74 19.9502a4.4992 4.4992 0 0 1-6.1408-1.6464zM2.3408 7.8956a4.485 4.485 0 0 1 2.3655-1.9728V11.6a.7664.7664 0 0 0 .3879.6765l5.8144 3.3543-2.0201 1.1685a.0757.0757 0 0 1-.071 0l-4.8303-2.7865A4.504 4.504 0 0 1 2.3408 7.8956zm16.0993 3.8558L12.5907 8.3829 14.6108 7.2144a.0757.0757 0 0 1 .071 0l4.8303 2.7913a4.4944 4.4944 0 0 1-.6765 8.1042v-5.6772a.79.79 0 0 0-.3927-.6813zm2.0107-3.0231l-.142-.0852-4.7735-2.7818a.7759.7759 0 0 0-.7854 0L9.409 9.2297V6.8974a.0662.0662 0 0 1 .0284-.0615l4.8303-2.7866a4.4992 4.4992 0 0 1 6.6802 4.66zM8.3065 12.863l-2.02-1.1638a.0804.0804 0 0 1-.038-.0567V6.0742a4.4992 4.4992 0 0 1 7.3757-3.4537l-.142.0805L8.704 5.459a.7948.7948 0 0 0-.3927.6813zm1.0976-2.3654l2.602-1.4998 2.6069 1.4998v2.9994l-2.5974 1.4997-2.6067-1.4997Z"
                fill="currentColor"
              />
            </svg>
          </span>
        </span>
        <span class="ai-btn-text">{{ generating ? '生成中…' : 'AI辅助生成' }}</span>
      </button>
    </div>

    <div class="edit-grid">
      <div class="edit-row">
        <label class="edit-label">标题</label>
        <input
          :value="title"
          class="edit-input"
          placeholder="一个有吸引力的标题（默认取 Skill 名）"
          @input="emit('update', 'title', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="edit-row half">
        <label class="edit-label">分类</label>
        <input
          :value="category"
          class="edit-input"
          placeholder="如 代码审查 / AI人格"
          @input="emit('update', 'category', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="edit-row half">
        <label class="edit-label">作者 / 人格</label>
        <input
          :value="author"
          class="edit-input"
          placeholder="默认发布者名"
          @input="emit('update', 'author', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="edit-row">
        <label class="edit-label">介绍正文（Markdown）</label>
        <div class="edit-editor">
          <MarkdownEditor
            :model-value="md || ''"
            @update:model-value="emit('update', 'md', $event)"
          />
        </div>
      </div>
    </div>
  </div>

  <!-- 查看态（文章样式） -->
  <article v-else class="intro-article">
    <h1 class="intro-title">{{ displayTitle }}</h1>
    <div class="intro-byline">
      <span class="intro-avatar">{{ authorInitial }}</span>
      <span v-if="displayAuthor" class="intro-author">{{ displayAuthor }}</span>
      <span v-if="displayCategory" class="intro-cat">{{ displayCategory }}</span>
    </div>
    <div class="intro-body">
      <MarkdownView :source="md" :placeholder="emptyPlaceholder || '暂无介绍，点击「编辑」补充。'" />
    </div>
  </article>
</template>

<style scoped>
/* —— 编辑态 —— */
.intro-edit {
  position: relative;
  max-width: 100%;
  overflow-x: clip;
}
.intro-toolbar {
  position: absolute;
  top: 0.2rem;
  right: -0.25rem;
  display: flex;
  justify-content: flex-end;
  width: 5.5rem;
  min-height: 4.5rem;
  padding: 1.2rem 1.5rem 0 0;
  box-sizing: border-box;
  z-index: 2;
}
.ai-btn {
  position: relative;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  padding: 0;
  border: none;
  background: transparent;
  color: #151717;
  cursor: pointer;
  overflow: visible;
  -webkit-tap-highlight-color: transparent;
}
.ai-btn:focus-visible {
  outline: 2px solid #151717;
  outline-offset: 6px;
  border-radius: 10px;
}
.ai-btn:disabled { cursor: wait; }

.ai-layer {
  position: absolute;
  inset: 0;
  display: block;
  transition: transform 0.3s ease;
}
.ai-layer-sheet {
  position: absolute;
  inset: 0;
  display: block;
  border: 1px solid transparent;
  border-radius: 12px;
  background: transparent;
  box-shadow: -1px 1px 3px rgba(16, 163, 127, 0);
  transition: transform 0.3s ease, opacity 0.3s ease, box-shadow 0.3s ease,
    border-color 0.3s ease, background-color 0.3s ease, color 0.3s ease;
}
.ai-layer-face {
  display: flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #151717;
}
.openai-icon {
  width: 23px;
  height: 23px;
  display: block;
}
.ai-btn-text {
  position: absolute;
  left: 50%;
  bottom: -5px;
  opacity: 0;
  color: #08745c;
  font-family: inherit;
  font-size: 0.78rem;
  font-weight: 600;
  white-space: nowrap;
  transform: translate(-50%, 100%);
  transition: bottom 0.3s ease, opacity 0.3s ease;
}

.ai-btn:hover:not(:disabled) .ai-layer,
.ai-btn:focus-visible .ai-layer,
.ai-btn.generating .ai-layer {
  transform: rotate(-35deg) skew(20deg);
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet,
.ai-btn:focus-visible .ai-layer-sheet,
.ai-btn.generating .ai-layer-sheet {
  border-color: #10a37f;
  background: #ffffff;
  box-shadow: -1px 1px 3px rgba(16, 163, 127, 0.42);
}
.ai-btn:hover:not(:disabled) .ai-layer-face,
.ai-btn:focus-visible .ai-layer-face,
.ai-btn.generating .ai-layer-face {
  background: #10a37f;
  color: #ffffff;
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet:nth-child(1),
.ai-btn:focus-visible .ai-layer-sheet:nth-child(1),
.ai-btn.generating .ai-layer-sheet:nth-child(1) {
  opacity: 0.2;
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet:nth-child(2),
.ai-btn:focus-visible .ai-layer-sheet:nth-child(2),
.ai-btn.generating .ai-layer-sheet:nth-child(2) {
  opacity: 0.4;
  transform: translate(3px, -3px);
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet:nth-child(3),
.ai-btn:focus-visible .ai-layer-sheet:nth-child(3),
.ai-btn.generating .ai-layer-sheet:nth-child(3) {
  opacity: 0.6;
  transform: translate(6px, -6px);
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet:nth-child(4),
.ai-btn:focus-visible .ai-layer-sheet:nth-child(4),
.ai-btn.generating .ai-layer-sheet:nth-child(4) {
  opacity: 0.8;
  transform: translate(9px, -9px);
}
.ai-btn:hover:not(:disabled) .ai-layer-sheet:nth-child(5),
.ai-btn:focus-visible .ai-layer-sheet:nth-child(5),
.ai-btn.generating .ai-layer-sheet:nth-child(5) {
  opacity: 1;
  transform: translate(12px, -12px);
}
.ai-btn:hover:not(:disabled) .ai-btn-text,
.ai-btn:focus-visible .ai-btn-text,
.ai-btn.generating .ai-btn-text {
  bottom: -3px;
  opacity: 1;
}

.edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.9rem 1rem;
}
.edit-grid > .edit-row:first-child {
  min-height: 4.75rem;
  padding-right: 5.75rem;
}
.edit-row {
  grid-column: 1 / -1;
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}
.edit-row.half { grid-column: span 1; }
.edit-label {
  font-size: 0.8rem;
  font-weight: 600;
  color: #6b7280;
}
.edit-input {
  width: 100%;
  padding: 0.68rem 0.85rem;
  background: #eef0f3;
  border: none;
  border-radius: 8px;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  box-sizing: border-box;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}
.edit-input:focus {
  outline: none;
  background: #ffffff;
  box-shadow: inset 0 0 0 2px #151717;
}
.edit-input::placeholder { color: #b6bcc4; }
.edit-editor {
  border: 1px solid #ebedf0;
  border-radius: 10px;
  overflow: hidden;
}

/* —— 查看态（文章样式）—— */
.intro-article { max-width: 760px; margin: 0 auto; }
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
.intro-body { font-size: 1rem; line-height: 1.8; color: #2c2f33; }

.spinner {
  display: inline-block;
  width: 0.9em;
  height: 0.9em;
  border: 2px solid rgba(255, 255, 255, 0.5);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 640px) {
  .edit-row.half { grid-column: 1 / -1; }
}
</style>
