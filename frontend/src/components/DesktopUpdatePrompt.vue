<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import BaseModal from '@/components/BaseModal.vue'
import {
  getDesktopBridge,
  type DesktopUpdateState,
} from '@/runtime/desktopBridge'

const visible = ref(false)
const installing = ref(false)
const installError = ref('')
const updateState = ref<DesktopUpdateState | null>(null)
let dismissedVersion = ''
let unsubscribe: (() => void) | null = null

const version = computed(() => updateState.value?.availableVersion ?? '')

function applyState(next: DesktopUpdateState) {
  updateState.value = next
  if (
    next.status === 'downloaded' &&
    next.availableVersion &&
    next.availableVersion !== dismissedVersion
  ) {
    installError.value = ''
    visible.value = true
  }
}

function postpone() {
  dismissedVersion = version.value
  visible.value = false
  installError.value = ''
}

async function installNow() {
  const updater = getDesktopBridge()?.update
  if (!updater || installing.value) return

  installing.value = true
  installError.value = ''
  try {
    const accepted = await updater.install()
    if (!accepted) {
      throw new Error('更新尚未下载完成，请稍后重试')
    }
  } catch (error) {
    installing.value = false
    installError.value = (error as Error)?.message || '启动安装失败，请稍后重试'
  }
}

onMounted(() => {
  const updater = getDesktopBridge()?.update
  if (!updater) return

  unsubscribe = updater.onStateChange(applyState)
  void updater.getState().then(applyState).catch((error: unknown) => {
    console.error('[desktop-update] 获取更新状态失败:', error)
  })
})

onBeforeUnmount(() => {
  unsubscribe?.()
  unsubscribe = null
})
</script>

<template>
  <BaseModal
    :model-value="visible"
    title="新版本已准备好"
    :width="460"
    :closable="!installing"
    :close-on-overlay="!installing"
    @update:model-value="postpone"
  >
    <div class="update-content">
      <div class="update-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="M12 4v11m0 0-4-4m4 4 4-4" />
          <path d="M5 18.5h14" />
        </svg>
      </div>
      <div class="update-copy">
        <p class="update-lead">
          Vibebara {{ version }} 已在后台下载完成。
        </p>
        <p class="update-note">
          立即重启即可完成安装，项目和个人数据不会受影响。
        </p>
      </div>
    </div>
    <p v-if="installError" class="update-error" role="alert">
      {{ installError }}
    </p>

    <template #footer>
      <button
        class="update-btn update-btn-secondary"
        type="button"
        :disabled="installing"
        @click="postpone"
      >
        稍后
      </button>
      <button
        class="update-btn update-btn-primary"
        type="button"
        :disabled="installing"
        @click="installNow"
      >
        {{ installing ? '正在重启…' : '立即重启安装' }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.update-content {
  display: flex;
  align-items: flex-start;
  gap: 14px;
}

.update-icon {
  width: 42px;
  height: 42px;
  flex: 0 0 42px;
  display: grid;
  place-items: center;
  border-radius: 10px;
  background: #f0f1ff;
  color: var(--primary, #6366f1);
}

.update-icon svg {
  width: 23px;
  height: 23px;
  stroke: currentColor;
  stroke-width: 1.8;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.update-copy {
  min-width: 0;
  padding-top: 1px;
}

.update-lead {
  margin: 0;
  color: #151717;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.55;
  overflow-wrap: anywhere;
}

.update-note {
  margin: 6px 0 0;
  color: #6b7280;
  font-size: 13px;
  line-height: 1.55;
}

.update-error {
  margin: 14px 0 0;
  padding: 9px 11px;
  border-radius: 8px;
  background: #fef2f2;
  color: #b91c1c;
  font-size: 13px;
  line-height: 1.5;
}

.update-btn {
  min-width: 76px;
  padding: 8px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  font-family: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.update-btn:disabled {
  cursor: wait;
  opacity: 0.6;
}

.update-btn-secondary {
  border-color: transparent;
  background: transparent;
  color: #151717;
}

.update-btn-secondary:hover:not(:disabled) {
  background: #f3f4f6;
}

.update-btn-primary {
  border-color: #151717;
  background: #151717;
  color: #ffffff;
}

.update-btn-primary:hover:not(:disabled) {
  border-color: #2d2f2f;
  background: #2d2f2f;
}

@media (max-width: 520px) {
  .update-content {
    gap: 11px;
  }

  .update-icon {
    width: 38px;
    height: 38px;
    flex-basis: 38px;
  }
}
</style>
