<script setup lang="ts">
import { confirmState, acceptConfirm, rejectConfirm } from '@/composables/useConfirmDialog'
import BaseModal from '@/components/BaseModal.vue'
</script>

<template>
  <BaseModal
    :model-value="confirmState.visible"
    :title="confirmState.title"
    :width="440"
    @update:model-value="rejectConfirm"
  >
    <p class="cd-message">{{ confirmState.message }}</p>

    <template #footer>
      <button class="cd-btn cd-btn-cancel" type="button" @click="rejectConfirm">
        {{ confirmState.cancelText }}
      </button>
      <button
        class="cd-btn"
        :class="confirmState.danger ? 'cd-btn-danger' : 'cd-btn-primary'"
        type="button"
        @click="acceptConfirm"
      >
        {{ confirmState.confirmText }}
      </button>
    </template>
  </BaseModal>
</template>

<style scoped>
.cd-message {
  font-size: 14px;
  color: #151717;
  line-height: 1.6;
  margin: 0;
  white-space: pre-line;
  word-break: break-word;
}

.cd-btn {
  padding: 7px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 9px;
  background: #ffffff;
  color: #6b7280;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.cd-btn:hover {
  border-color: #d1d5db;
  color: #151717;
}

.cd-btn-cancel {
  border: 0;
  background: transparent;
  color: #000000;
}

.cd-btn-cancel:hover {
  border-color: transparent;
  background: #f3f4f6;
  color: #000000;
}

.cd-btn-primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
  font-weight: 600;
}

.cd-btn-primary:hover {
  background: #2d2f2f;
  border-color: #2d2f2f;
  color: #ffffff;
}

.cd-btn-danger {
  background: #dc2626;
  border-color: #dc2626;
  color: #ffffff;
  font-weight: 600;
}

.cd-btn-danger:hover {
  background: #b91c1c;
  border-color: #b91c1c;
  color: #ffffff;
}
</style>
