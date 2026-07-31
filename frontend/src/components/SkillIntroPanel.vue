<script setup lang="ts">
import { ref, computed } from 'vue'
import MarkdownView from '@/components/MarkdownView.vue'
import MarkdownEditor from '@/components/MarkdownEditor.vue'
import { toast } from '@/composables/useToast'
import { generateSkillIntroDraft } from '@/api/skillStore'

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
    fallbackTitle?: string
    // 是否提供「AI 辅助生成」（市场条目编辑无对应源 Skill，关闭即可）。
    aiAssist?: boolean
    // 查看态空正文占位文案。
    emptyPlaceholder?: string
  }>(),
  { aiAssist: true },
)

const emit = defineEmits<{
  (e: 'update', field: 'title' | 'author' | 'category' | 'md', value: string): void
}>()

const generating = ref(false)

const displayTitle = computed(() => (props.title || '').trim() || props.fallbackTitle || '')
const displayAuthor = computed(() => (props.author || '').trim())
const displayCategory = computed(() => (props.category || '').trim())
const authorInitial = computed(() => (displayAuthor.value || '?').slice(0, 1).toUpperCase())

async function aiGenerate() {
  if (generating.value || !props.skillId) {
    if (!props.skillId) toast.error('请先保存 Skill 后再使用 AI 辅助生成')
    return
  }
  generating.value = true
  try {
    const res = await generateSkillIntroDraft(props.skillId)
    if (res.success && res.draft) {
      if (res.draft.title) emit('update', 'title', res.draft.title)
      if (res.draft.category) emit('update', 'category', res.draft.category)
      if (res.draft.intro_md) emit('update', 'md', res.draft.intro_md)
      toast.success('已生成介绍草稿，可继续编辑')
    } else {
      toast.error(res.error || 'AI 生成失败，可手动填写')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e?.message || 'AI 生成失败，可手动填写')
  } finally {
    generating.value = false
  }
}
</script>

<template>
  <!-- 编辑态 -->
  <div v-if="editing" class="intro-edit">
    <div v-if="aiAssist" class="intro-toolbar">
      <button class="ai-btn" :disabled="generating" @click="aiGenerate">
        <span v-if="generating" class="spinner" />
        {{ generating ? '生成中…' : 'AI 辅助生成' }}
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
.intro-edit { max-width: 100%; }
.intro-toolbar {
  display: flex;
  justify-content: flex-end;
  margin-bottom: 0.85rem;
}
.ai-btn {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.45rem 0.95rem;
  border: 1px solid #4f46e5;
  border-radius: 9px;
  background: #4f46e5;
  color: #ffffff;
  font-size: 0.85rem;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease;
}
.ai-btn:hover:not(:disabled) { background: #4338ca; border-color: #4338ca; }
.ai-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.edit-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.9rem 1rem;
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
  padding: 0.55rem 0.75rem;
  background: #ffffff;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  color: #151717;
  font-size: 0.88rem;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.15s ease;
}
.edit-input:focus { outline: none; border-color: #151717; }
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
