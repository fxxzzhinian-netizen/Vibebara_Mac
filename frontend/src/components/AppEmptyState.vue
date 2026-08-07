<script setup lang="ts">
import emptyImg from '@/img/status/empty.png'

withDefaults(
  defineProps<{
    title: string
    description?: string
    image?: string
    compact?: boolean
  }>(),
  {
    image: emptyImg,
    compact: false,
  },
)
</script>

<template>
  <div class="app-empty-state" :class="{ compact }">
    <img :src="image" alt="" draggable="false" />
    <h2>{{ title }}</h2>
    <p v-if="description">{{ description }}</p>
  </div>
</template>

<style scoped>
.app-empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 4.5rem 1rem 3rem;
  text-align: center;
}

.app-empty-state img {
  width: min(420px, 86vw);
  height: auto;
  margin-top: -1.25rem;
  user-select: none;
  -webkit-user-drag: none;
}

.app-empty-state h2 {
  margin: -3.875rem 0 0;
  color: #303442;
  font-size: 1.375rem;
  font-weight: 600;
  line-height: 1.5;
  letter-spacing: 0.01em;
}

.app-empty-state p {
  margin: 0.9rem 0 0;
  color: #9ca3af;
  font-size: 0.9375rem;
  font-weight: 400;
  line-height: 1.5;
}

.app-empty-state.compact {
  padding: 2.75rem 1rem 2rem;
}

.app-empty-state.compact img {
  width: min(320px, 80vw);
  margin-top: -1rem;
}

.app-empty-state.compact h2 {
  margin-top: -3rem;
  font-size: 1.125rem;
}

.app-empty-state.compact p {
  margin-top: 0.6rem;
  font-size: 0.8125rem;
}
</style>
