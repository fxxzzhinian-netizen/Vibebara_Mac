<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { resolveAvatarUrl } from '@/api/auth'

const props = withDefaults(
  defineProps<{
    name?: string
    src?: string | null
    size?: number
    alt?: string
  }>(),
  {
    name: '',
    src: null,
    size: 42,
    alt: '',
  },
)

const imageFailed = ref(false)
const imageUrl = computed(() => resolveAvatarUrl(props.src))
const initial = computed(() => (props.name.trim().slice(0, 1) || '?').toUpperCase())
const avatarStyle = computed(() => ({
  width: `${props.size}px`,
  height: `${props.size}px`,
  fontSize: `${Math.max(13, props.size * 0.38)}px`,
}))

watch(
  () => props.src,
  () => {
    imageFailed.value = false
  },
)
</script>

<template>
  <span class="user-avatar" :style="avatarStyle" role="img" :aria-label="alt || name">
    <img
      v-if="imageUrl && !imageFailed"
      :src="imageUrl"
      :alt="alt || name"
      @error="imageFailed = true"
    />
    <span v-else aria-hidden="true">{{ initial }}</span>
  </span>
</template>

<style scoped>
.user-avatar {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border-radius: 50%;
  background: #151717;
  color: #ffffff;
  font-weight: 600;
  line-height: 1;
  user-select: none;
}

.user-avatar img {
  width: 100%;
  height: 100%;
  display: block;
  object-fit: cover;
}
</style>
