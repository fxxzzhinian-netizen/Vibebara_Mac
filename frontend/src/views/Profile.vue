<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import BaseModal from '@/components/BaseModal.vue'
import BaseSelect, { type SelectOption } from '@/components/BaseSelect.vue'
import UserAvatar from '@/components/UserAvatar.vue'
import { useAuthStore } from '@/stores/authStore'
import { toast } from '@/composables/useToast'
import { confirmDialog } from '@/composables/useConfirmDialog'
import type { UpdateProfilePayload } from '@/api/auth'
import { isDesktop } from '@/runtime/desktopBridge'

const props = defineProps<{
  modelValue: boolean
}>()

const emit = defineEmits<{
  (event: 'update:modelValue', value: boolean): void
}>()

const desktop = isDesktop()

type ProfileKey =
  | 'display_name'
  | 'email'
  | 'phone'
  | 'gender'
  | 'birthday'
  | 'location'

interface ProfileField {
  key: ProfileKey
  label: string
  value: string | null
  display: string
  placeholder: string
  inputType: 'text' | 'email' | 'tel' | 'date' | 'select'
  icon: string
}

const authStore = useAuthStore()
const user = computed(() => authStore.user)
const displayName = computed(
  () => user.value?.display_name || user.value?.username || '未登录',
)
const loading = ref(!authStore.user)

const genderLabels: Record<string, string> = {
  male: '男',
  female: '女',
  other: '其他',
  unspecified: '不公开',
}

const genderOptions: SelectOption[] = [
  { label: '不公开', value: 'unspecified' },
  { label: '男', value: 'male' },
  { label: '女', value: 'female' },
  { label: '其他', value: 'other' },
]

const fields = computed<ProfileField[]>(() => [
  {
    key: 'display_name',
    label: '昵称',
    value: user.value?.display_name ?? '',
    display: user.value?.display_name || '未设置',
    placeholder: '输入昵称',
    inputType: 'text',
    icon: 'M594.3 561.6H428.4c-155.3 0-281.7 121.2-281.7 270.2v15.9c0 79.5 124.3 79.5 281.7 79.5h165.9c151.1 0 281.7 0 281.7-79.5v-15.9c0-149-126.4-270.2-281.7-270.2z M511.3 313.4m-215.8 0a215.8 215.8 0 1 0 431.6 0 215.8 215.8 0 1 0-431.6 0Z',
  },
  {
    key: 'email',
    label: '邮箱',
    value: user.value?.email ?? '',
    display: user.value?.email || '未设置',
    placeholder: 'name@example.com',
    inputType: 'email',
    icon: 'M870.7 176.7H153.9c-49.5 0-89.6 40.1-89.6 89.6v492.8c0 49.5 40.1 89.6 89.6 89.6h716.8c49.5 0 89.6-40.1 89.6-89.6V266.3c0-49.5-40.1-89.6-89.6-89.6zM586.9 498.9c-35.2 18.2-92.3 18.2-127.5 0L162.8 345.5c8.1-14.3 21.3-25.1 37-30.5l259.6 137c35.2 18.2 92.3 18.2 127.5 0l249.8-131.9c13.3 7.7 23.9 19.7 29.4 34.3L586.9 498.9z',
  },
  {
    key: 'phone',
    label: '手机号',
    value: user.value?.phone ?? '',
    display: user.value?.phone || '未设置',
    placeholder: '输入手机号',
    inputType: 'tel',
    icon: 'M512.3 583.8c-38.2 0-69.2 31.7-69.2 70.7s31 70.6 69.2 70.6 69.2-31.6 69.2-70.6c0-39-31-70.7-69.2-70.7z m138.4-211.9h-69.2v35.3H443.1v-35.3H374v35.3L166.4 654.5v141.3c0 39 31 70.7 69.2 70.7h553.5c38.2 0 69.2-31.7 69.2-70.7V654.5L650.7 407.2v-35.3zM512.3 795.8c-76.4 0-138.3-63.3-138.3-141.3 0-78 61.9-141.3 138.3-141.3s138.4 63.3 138.4 141.3c0 78-62 141.3-138.4 141.3z m415-459.3c-0.9-37.1-23.5-78.8-69-105.9-117.5-70-345.9-70.7-345.9-70.7s-228.5 0.7-346 70.7C120.5 258 98 300 97.3 337.3c-1 55.6 46.8 100.7 138.2 70 86.5-29.1 51.7-84.6 103.8-106 88.5-36.2 172.9-35.3 172.9-35.3s84.8-1.2 173 35.3c52 21.5 17.3 76.9 103.8 106 92 30.8 139.8-14.8 138.3-70.8z',
  },
  {
    key: 'gender',
    label: '性别',
    value: user.value?.gender ?? '',
    display: user.value?.gender ? genderLabels[user.value.gender] || '未设置' : '未设置',
    placeholder: '选择性别',
    inputType: 'select',
    icon: 'M594.3 561.6H428.4c-155.3 0-281.7 121.2-281.7 270.2v15.9c0 79.5 124.3 79.5 281.7 79.5h165.9c151.1 0 281.7 0 281.7-79.5v-15.9c0-149-126.4-270.2-281.7-270.2z M511.3 313.4m-215.8 0a215.8 215.8 0 1 0 431.6 0 215.8 215.8 0 1 0-431.6 0Z',
  },
  {
    key: 'birthday',
    label: '生日',
    value: user.value?.birthday ?? '',
    display: formatBirthday(user.value?.birthday),
    placeholder: '选择生日',
    inputType: 'date',
    icon: 'M266.7 337.1c27.9 0 50.6-27.8 50.6-62.2v-69.8c0-34.3-22.6-62.2-50.6-62.2-27.9 0-50.6 27.8-50.6 62.2v69.8c0.1 34.4 22.7 62.2 50.6 62.2z m342.5 316.8c52.2-52.2 138-51.9 190.8-0.7 2.1-0.6 67.2-57.6 67.2-57.6l-0.3-321.5c0-60.9-54.9-57-54.9-57h-28s0.1 57 0 99.4c-0.1 42.4-41.4 42.9-41.4 42.9s-40.4-0.1-85.7 0c-45.3 0.1-43.2-42.3-43.2-42.3v-99.9H354.3v98.9c0 44.3-43 43.3-43 43.3s-43 0.1-85 0-42.6-43.4-42.6-43.4v-98.8h-28.3c-53.9 0-57.1 56.8-57.1 56.8s0.1 492.6 0.1 549.1 57.2 57 57.2 57h496l-34.7-38.2c-52.9-52.7-60.4-135.2-7.7-188zM699 337.1c27.9 0 50.6-27.8 50.6-62.2v-69.8c0-34.3-24.5-62.2-52.5-62.2-27.9 0-48.7 27.8-48.6 62.2v69.8c0 34.4 22.6 62.2 50.5 62.2z m216.5 375.2c-19.7-19.8-55.4-16.1-79.7 8.2l-39.6 39.7-37.2-41.1c-24.3-24.3-59.9-27.9-79.7-8.2-19.7 19.8-16.1 55.5 8.2 79.7l67.2 67.3c1.8 1.8 3.8 3.6 5.8 5.2 1.2 1.5 2.4 3 3.8 4.4 13.5 13.5 30.7 16.1 50.3 8.6 2.1-0.7 4.1-1.6 6.1-2.7 6.9-3.4 13.6-8.1 19.5-14.1l67.2-67.3c24.2-24.2 27.9-59.9 8.1-79.7z',
  },
  {
    key: 'location',
    label: '居住地',
    value: user.value?.location ?? '',
    display: user.value?.location || '未设置',
    placeholder: '输入国家、城市或地区',
    inputType: 'text',
    icon: 'M794.7 178C638.8 25 385.9 25 230 178 74 331.1 74 579.3 230 732.4l282.4 226.8 282.4-226.8c155.9-153.1 155.9-401.3-0.1-554.4zM512.4 623.2c-94.5 0-171.1-75.2-171.1-168s76.6-168 171.1-168 171.1 75.2 171.1 168-76.6 168-171.1 168z',
  },
])

const activeField = ref<ProfileField | null>(null)
const draftValue = ref('')
const fieldError = ref('')
const saving = ref(false)
const today = new Date().toISOString().slice(0, 10)

const editTitle = computed(() =>
  activeField.value ? `编辑${activeField.value.label}` : '编辑个人信息',
)

function formatBirthday(value?: string | null): string {
  if (!value) return '未设置'
  const parts = value.slice(0, 10).split('-')
  if (parts.length !== 3) return value
  return `${Number(parts[0])}年${Number(parts[1])}月${Number(parts[2])}日`
}

function openEditor(field: ProfileField) {
  activeField.value = field
  draftValue.value = field.value || ''
  fieldError.value = ''
}

function closeEditor() {
  if (saving.value) return
  activeField.value = null
  fieldError.value = ''
}

function validateDraft(): string {
  const field = activeField.value
  if (!field) return '请选择要编辑的资料'
  const value = draftValue.value.trim()
  if (field.key === 'display_name' && !value) return '昵称不能为空'
  if (field.key === 'display_name' && value.length > 128) return '昵称不能超过 128 个字符'
  if (field.key === 'email' && value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value)) {
    return '请输入有效的邮箱地址'
  }
  if (field.key === 'phone' && value && value.length > 32) return '手机号不能超过 32 个字符'
  if (field.key === 'location' && value.length > 256) return '居住地不能超过 256 个字符'
  return ''
}

async function submitField() {
  if (!activeField.value || saving.value) return
  fieldError.value = validateDraft()
  if (fieldError.value) return

  saving.value = true
  const key = activeField.value.key
  const trimmed = draftValue.value.trim()
  const payload = {
    [key]: key === 'display_name' ? trimmed : trimmed || null,
  } as UpdateProfilePayload
  const result = await authStore.saveProfile(payload)
  saving.value = false

  if (!result.success) {
    fieldError.value = result.error || '保存失败，请稍后重试'
    return
  }
  activeField.value = null
  toast.success('个人信息已更新')
}

const avatarOpen = ref(false)
const avatarInput = ref<HTMLInputElement | null>(null)
const selectedAvatar = ref<File | null>(null)
const previewUrl = ref('')
const avatarError = ref('')
const avatarSaving = ref(false)

function openAvatarDialog() {
  cleanupPreview()
  selectedAvatar.value = null
  avatarError.value = ''
  avatarOpen.value = true
}

defineExpose({
  openAvatarDialog,
})

function closeAvatarDialog() {
  if (avatarSaving.value) return
  avatarOpen.value = false
  cleanupPreview()
  selectedAvatar.value = null
}

function chooseAvatar() {
  avatarInput.value?.click()
}

function onAvatarSelected(event: Event) {
  const file = (event.target as HTMLInputElement).files?.[0]
  if (!file) return
  avatarError.value = ''
  if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
    avatarError.value = '仅支持 JPG、PNG 或 WebP 图片'
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    avatarError.value = '图片大小不能超过 5 MB'
    return
  }
  cleanupPreview()
  selectedAvatar.value = file
  previewUrl.value = URL.createObjectURL(file)
  ;(event.target as HTMLInputElement).value = ''
}

function cleanupPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

async function submitAvatar() {
  if (!selectedAvatar.value || avatarSaving.value) return
  avatarSaving.value = true
  avatarError.value = ''
  const result = await authStore.saveAvatar(selectedAvatar.value)
  avatarSaving.value = false
  if (!result.success) {
    avatarError.value = result.error || '头像上传失败'
    return
  }
  closeAvatarDialog()
  toast.success('头像已更新')
}

async function removeAvatar() {
  if (!user.value?.avatar_url || avatarSaving.value) return
  const confirmed = await confirmDialog({
    title: '移除头像',
    message: '移除后将显示昵称首字母作为头像。',
    confirmText: '移除',
    danger: true,
  })
  if (!confirmed) return

  avatarSaving.value = true
  const result = await authStore.removeAvatar()
  avatarSaving.value = false
  if (!result.success) {
    avatarError.value = result.error || '头像移除失败'
    return
  }
  closeAvatarDialog()
  toast.success('头像已移除')
}

let previousBodyOverflow = ''

function closeDrawer() {
  if (saving.value || avatarSaving.value) return
  activeField.value = null
  avatarOpen.value = false
  cleanupPreview()
  selectedAvatar.value = null
  emit('update:modelValue', false)
}

function onDrawerKeydown(event: KeyboardEvent) {
  if (
    event.key === 'Escape' &&
    !activeField.value &&
    !avatarOpen.value
  ) {
    closeDrawer()
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      previousBodyOverflow = document.body.style.overflow
      document.body.style.overflow = 'hidden'
      window.addEventListener('keydown', onDrawerKeydown)
      if (!authStore.user) await authStore.fetchMe()
      loading.value = false
    } else {
      document.body.style.overflow = previousBodyOverflow
      window.removeEventListener('keydown', onDrawerKeydown)
    }
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  cleanupPreview()
  document.body.style.overflow = previousBodyOverflow
  window.removeEventListener('keydown', onDrawerKeydown)
})
</script>

<template>
  <Teleport to="body">
    <Transition name="profile-drawer">
      <div
        v-if="modelValue"
        class="profile-drawer-layer"
        role="presentation"
        @click.self="closeDrawer"
      >
        <aside
          :class="['profile-drawer-panel', { 'is-desktop': desktop }]"
          role="dialog"
          aria-modal="true"
          aria-label="个人信息"
        >
          <div class="profile-drawer-body">
            <section v-if="loading" class="profile-card loading-card" aria-label="正在加载">
              <div v-for="i in 5" :key="i" class="skeleton-row">
                <span class="sk-icon"></span>
                <span class="sk-copy"></span>
              </div>
            </section>

            <template v-else-if="user">
              <section class="profile-section" aria-label="个人资料字段">
                <div class="settings-grid">
                  <button class="info-row avatar-row" type="button" @click="openAvatarDialog">
                  <span class="row-icon" aria-hidden="true">
                    <svg class="camera-icon" viewBox="0 0 1024 1024">
                      <path d="M896.4 296.6l-0.1 0.1c-20.5-21.1-48.8-32.7-78.2-32.1h-96.2l-22.1-58.2c-6.3-14.5-16.5-27-29.5-36-12.9-9.8-28.5-15.4-44.6-16H404.8c-16 0.5-31.5 6.1-44.1 16-13.1 9-23.3 21.5-29.7 36l-24 58.2h-98.2c-29.4-0.6-57.7 11-78.2 32.1-21.1 20.5-32.7 48.8-32.1 78.1v386.9c-0.6 29.4 11 57.7 32.1 78.2 20.5 21.1 48.8 32.7 78.2 32.1h609.4c29.3 0.2 57.5-11.4 78.2-32.1 20.7-20.7 32.3-48.9 32.1-78.2V374.8c0.6-29.4-11-57.7-32.1-78.2zM513.5 743.7c-100.7 0-182.4-81.6-182.4-182.3 0-100.7 81.6-182.4 182.3-182.4 100.7 0 182.4 81.6 182.3 182.3-0.3 100.6-81.7 182.1-182.3 182.4z m0-302.7C445.8 441 391 495.9 391 563.5c0 67.7 54.9 122.5 122.5 122.5 67.7 0 122.5-54.9 122.5-122.5 0.3-32.6-12.5-63.9-35.6-86.9-23-23.1-54.3-35.9-86.9-35.6z" />
                    </svg>
                  </span>
                  <span class="row-label">个人头像</span>
                  <span class="row-value">点击更换或移除头像</span>
                  <UserAvatar :name="displayName" :src="user.avatar_url" :size="56" />
                  <svg class="row-chevron" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="m9 18 6-6-6-6" />
                  </svg>
                </button>

                  <button
                    v-for="field in fields"
                    :key="field.key"
                    class="info-row"
                    type="button"
                    @click="openEditor(field)"
                  >
                    <span class="row-icon" aria-hidden="true">
                      <svg viewBox="0 0 1024 1024"><path :d="field.icon" /></svg>
                    </span>
                    <span class="row-label">{{ field.label }}</span>
                    <span class="row-value" :class="{ empty: field.display === '未设置' }">
                      {{ field.display }}
                    </span>
                    <svg class="row-chevron" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="m9 18 6-6-6-6" />
                    </svg>
                  </button>
                </div>
              </section>
            </template>
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>

    <BaseModal
      :model-value="!!activeField"
      :title="editTitle"
      :closable="!saving"
      :close-on-overlay="!saving"
      :body-scroll="false"
      @update:model-value="!$event && closeEditor()"
    >
      <div v-if="activeField" class="edit-form">
        <label :for="`profile-${activeField.key}`">{{ activeField.label }}</label>
        <BaseSelect
          v-if="activeField.key === 'gender'"
          v-model="draftValue"
          :options="genderOptions"
          :placeholder="activeField.placeholder"
          :disabled="saving"
        />
        <input
          v-else
          :id="`profile-${activeField.key}`"
          v-model="draftValue"
          :type="activeField.inputType"
          :placeholder="activeField.placeholder"
          :max="activeField.key === 'birthday' ? today : undefined"
          :disabled="saving"
          @keyup.enter="submitField"
        />
        <p class="field-help">
          {{ activeField.key === 'display_name' ? '昵称会显示在顶部导航和协作成员列表中。' : '留空保存即可清除此项。' }}
        </p>
        <p v-if="fieldError" class="form-error" role="alert">{{ fieldError }}</p>
      </div>
      <template #footer>
        <button class="dialog-btn" type="button" :disabled="saving" @click="closeEditor">
          取消
        </button>
        <button class="dialog-btn primary" type="button" :disabled="saving" @click="submitField">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </template>
    </BaseModal>

    <BaseModal
      :model-value="avatarOpen"
      title="设置个人头像"
      :closable="!avatarSaving"
      :close-on-overlay="!avatarSaving"
      @update:model-value="!$event && closeAvatarDialog()"
    >
      <div class="avatar-editor">
        <div class="avatar-preview-ring">
          <UserAvatar
            :name="displayName"
            :src="previewUrl || user?.avatar_url"
            :size="112"
          />
        </div>
        <div class="avatar-copy">
          <strong>{{ selectedAvatar ? '新头像预览' : '个人头像' }}</strong>
          <p>建议使用清晰的正方形图片，上传后会自动居中裁切。</p>
        </div>
        <input
          ref="avatarInput"
          class="visually-hidden"
          type="file"
          accept="image/jpeg,image/png,image/webp"
          @change="onAvatarSelected"
        />
        <button class="choose-file-btn" type="button" :disabled="avatarSaving" @click="chooseAvatar">
          选择图片
        </button>
        <p class="avatar-rules">JPG、PNG 或 WebP，最大 5 MB</p>
        <p v-if="avatarError" class="form-error" role="alert">{{ avatarError }}</p>
      </div>
      <template #footer>
        <button
          v-if="user?.avatar_url"
          class="dialog-btn danger"
          type="button"
          :disabled="avatarSaving"
          @click="removeAvatar"
        >
          移除头像
        </button>
        <span class="footer-spacer"></span>
        <button class="dialog-btn" type="button" :disabled="avatarSaving" @click="closeAvatarDialog">
          取消
        </button>
        <button
          class="dialog-btn primary"
          type="button"
          :disabled="avatarSaving || !selectedAvatar"
          @click="submitAvatar"
        >
          {{ avatarSaving ? '上传中…' : '保存头像' }}
        </button>
      </template>
    </BaseModal>
</template>

<style scoped>
.profile-drawer-layer {
  position: fixed;
  inset: 0;
  z-index: 900;
  display: flex;
  justify-content: flex-end;
  background: rgba(21, 23, 23, 0.28);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
}

.profile-drawer-panel {
  width: 33.333vw;
  min-width: 380px;
  max-width: 560px;
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-left: 0;
  background: #f7f8fa;
  box-shadow: -16px 0 48px rgba(21, 23, 23, 0.14);
  color: #202124;
}

.profile-drawer-panel.is-desktop {
  padding-top: 40px;
}

.profile-drawer-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 20px 28px;
  background: #f7f8fa;
}

.profile-drawer-enter-active,
.profile-drawer-leave-active {
  transition: background 0.22s ease;
}

.profile-drawer-enter-active .profile-drawer-panel,
.profile-drawer-leave-active .profile-drawer-panel {
  transition: transform 0.24s cubic-bezier(0.4, 0, 0.2, 1);
}

.profile-drawer-enter-from,
.profile-drawer-leave-to {
  background: rgba(21, 23, 23, 0);
}

.profile-drawer-enter-from .profile-drawer-panel,
.profile-drawer-leave-to .profile-drawer-panel {
  transform: translateX(100%);
}

.profile-card {
  overflow: hidden;
  border: 0;
  border-radius: 16px;
  background: #ffffff;
}

.settings-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: 10px;
}

.info-row {
  width: 100%;
  min-height: 82px;
  display: grid;
  grid-template-columns: 34px minmax(0, 1fr) auto 16px;
  grid-template-rows: auto auto;
  align-items: center;
  column-gap: 11px;
  padding: 13px 14px;
  border: 0;
  border-radius: 14px;
  background: #ffffff;
  color: #202124;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s ease;
}

.info-row:hover {
  background: #eef3fb;
}

.info-row:focus-visible {
  position: relative;
  z-index: 1;
  outline: 2px solid #202124;
  outline-offset: 2px;
}

.avatar-row {
  grid-column: 1 / -1;
  min-height: 94px;
}

.row-icon {
  grid-column: 1;
  grid-row: 1 / span 2;
  width: 34px;
  height: 34px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  color: #5f6368;
}

.row-icon svg {
  width: 27px;
  height: 27px;
  fill: currentColor;
  stroke: none;
}

.row-icon svg.camera-icon {
  width: 29px;
  height: 29px;
  fill: currentColor;
  stroke: none;
}

.row-label {
  grid-column: 2;
  grid-row: 1;
  align-self: end;
  color: #3c4043;
  font-size: 13px;
  font-weight: 600;
}

.row-value {
  grid-column: 2;
  grid-row: 2;
  align-self: start;
  min-width: 0;
  overflow: hidden;
  color: #3c4043;
  font-size: 13px;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-value.empty {
  color: #9aa0a6;
}

.row-chevron {
  grid-column: 4;
  grid-row: 1 / span 2;
  width: 17px;
  height: 17px;
  fill: none;
  stroke: #9aa0a6;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}

.avatar-row .user-avatar {
  grid-column: 3;
  grid-row: 1 / span 2;
}

.loading-card {
  display: grid;
  gap: 10px;
  padding: 0;
  background: transparent;
}

.skeleton-row {
  height: 68px;
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 0 16px;
  border-radius: 14px;
  background: #ffffff;
}

.sk-icon,
.sk-copy {
  display: block;
  background: linear-gradient(90deg, #f1f2f3 25%, #e7e9eb 37%, #f1f2f3 63%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite;
}

.sk-icon {
  width: 24px;
  height: 24px;
  border-radius: 7px;
}

.sk-copy {
  width: 42%;
  height: 14px;
  border-radius: 5px;
}

@keyframes shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: 0 0; }
}

.edit-form label {
  display: block;
  margin-bottom: 8px;
  color: #3c4043;
  font-size: 13px;
  font-weight: 600;
}

.edit-form input {
  width: 100%;
  height: 44px;
  padding: 0 13px;
  border: 2px solid #e1e4e8;
  border-radius: 10px;
  outline: none;
  background: #ffffff;
  color: #202124;
  font: inherit;
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.edit-form input:focus {
  border-color: #202124;
  box-shadow: 0 0 0 3px rgba(32, 33, 36, 0.07);
}

.edit-form input:disabled {
  background: #f3f4f6;
  cursor: wait;
}

.field-help,
.avatar-rules {
  margin: 9px 0 0;
  color: #8b929b;
  font-size: 12px;
  line-height: 1.5;
}

.form-error {
  margin: 10px 0 0;
  color: #d93025;
  font-size: 13px;
  line-height: 1.5;
}

.dialog-btn,
.choose-file-btn {
  min-height: 36px;
  padding: 0 15px;
  border: none;
  border-radius: 9px;
  background: #f1f3f4;
  color: #4b5563;
  font: inherit;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.dialog-btn:hover:not(:disabled),
.choose-file-btn:hover:not(:disabled) {
  background: #e8eaed;
  color: #202124;
}

.dialog-btn:focus-visible,
.choose-file-btn:focus-visible {
  outline: 2px solid #202124;
  outline-offset: 2px;
}

.dialog-btn.primary {
  background: #202124;
  color: #ffffff;
}

.dialog-btn.primary:hover:not(:disabled) {
  background: #34373a;
  color: #ffffff;
}

.dialog-btn.danger {
  background: transparent;
  color: #d93025;
}

.dialog-btn.danger:hover:not(:disabled) {
  background: #fdf2f1;
  color: #b3261e;
}

.dialog-btn:disabled,
.choose-file-btn:disabled {
  opacity: 0.48;
  cursor: not-allowed;
}

.footer-spacer {
  flex: 1;
}

.avatar-editor {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 8px 0 2px;
  text-align: center;
}

.avatar-preview-ring {
  display: inline-flex;
  padding: 4px;
  border: 1px solid #e2e5e9;
  border-radius: 50%;
  background: #ffffff;
  box-shadow: 0 3px 14px rgba(32, 33, 36, 0.1);
}

.avatar-copy {
  margin: 18px 0 15px;
}

.avatar-copy strong {
  color: #202124;
  font-size: 15px;
  font-weight: 600;
}

.avatar-copy p {
  max-width: 320px;
  margin: 6px 0 0;
  color: #80868b;
  font-size: 13px;
  line-height: 1.55;
}

.choose-file-btn {
  min-height: 38px;
  color: #202124;
}

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 680px) {
  .profile-drawer-panel {
    width: min(100vw, 480px);
    min-width: 0;
    max-width: none;
  }

  .profile-drawer-body {
    padding: 16px 16px 24px;
  }

  .info-row {
    padding-inline: 14px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .profile-drawer-enter-active,
  .profile-drawer-leave-active,
  .profile-drawer-enter-active .profile-drawer-panel,
  .profile-drawer-leave-active .profile-drawer-panel {
    transition-duration: 0.01ms;
  }
}
</style>
