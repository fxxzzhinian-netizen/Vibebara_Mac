<script setup lang="ts">
import { ref } from 'vue'
import { fileIconUrl, type ResTreeNode } from './resourceTree'

const props = defineProps<{ node: ResTreeNode; depth: number; activePath: string }>()
const emit = defineEmits<{ (e: 'select', path: string): void }>()

const open = ref(true)

function onClick() {
  if (props.node.isDir) {
    open.value = !open.value
  } else {
    emit('select', props.node.path)
  }
}
</script>

<template>
  <div class="rt-node">
    <div
      class="rt-row"
      :class="{ active: !node.isDir && node.path === activePath }"
      :style="{ paddingLeft: depth * 14 + 4 + 'px' }"
      @click="onClick"
    >
      <span v-if="node.isDir" class="rt-caret">{{ open ? '▾' : '▸' }}</span>
      <span v-if="node.isDir" class="rt-icon">{{ open ? '📂' : '📁' }}</span>
      <img v-else class="rt-icon rt-icon-svg" :src="fileIconUrl(node.name)" alt="" aria-hidden="true" />
      <span class="rt-name">{{ node.name }}</span>
    </div>
    <div v-if="node.isDir && open && node.children && node.children.length" class="rt-children">
      <ResourceTreeNode
        v-for="c in node.children"
        :key="c.path"
        :node="c"
        :depth="depth + 1"
        :active-path="activePath"
        @select="emit('select', $event)"
      />
    </div>
  </div>
</template>

<style scoped>
.rt-row {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  padding-top: 0.32rem;
  padding-bottom: 0.32rem;
  padding-right: 0.5rem;
  border-radius: 7px;
  cursor: pointer;
  font-size: 0.9rem;
  color: #374151;
  user-select: none;
  transition: background 0.12s ease;
}
.rt-row:hover { background: #f3f4f6; }
.rt-row.active { background: #eef2ff; color: #4338ca; }

.rt-caret {
  flex-shrink: 0;
  width: 0.85rem;
  text-align: center;
  font-size: 0.7rem;
  color: #9ca3af;
}

.rt-icon { flex-shrink: 0; font-size: 0.92rem; }
.rt-icon-svg {
  width: 1.8rem;
  height: 1.8rem;
  display: block;
  align-self: center;
  object-fit: contain;
}

.rt-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 0.85rem;
  line-height: 1.3rem;
}
</style>
