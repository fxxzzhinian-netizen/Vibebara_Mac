<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/authStore'
import { toast } from '@/composables/useToast'
import SliderCaptcha from '@/components/SliderCaptcha.vue'
import BaseModal from '@/components/BaseModal.vue'
import logoUrl from '@/img/logo.png'

const router = useRouter()
const authStore = useAuthStore()

const mode = ref<'login' | 'register'>('login')
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const inviteCode = ref('')
const captchaToken = ref('')
const loading = ref(false)
const showCaptcha = ref(false)
const showPassword = ref(false)
const showConfirmPassword = ref(false)

function switchMode(target: 'login' | 'register') {
  if (mode.value === target) return
  mode.value = target
  captchaToken.value = ''
}

function validateFields(): boolean {
  if (!username.value || !password.value) {
    toast.warning('请输入用户名和密码')
    return false
  }
  if (mode.value === 'register') {
    if (!inviteCode.value.trim()) {
      toast.warning('请输入邀请码')
      return false
    }
    if (password.value !== confirmPassword.value) {
      toast.warning('两次输入的密码不一致')
      return false
    }
  }
  return true
}

// 点击登录/注册：先做字段校验，通过后弹出滑块验证
function handleSubmit() {
  if (!validateFields()) return
  captchaToken.value = ''
  showCaptcha.value = true
}

async function onCaptchaVerified(token: string) {
  captchaToken.value = token
  showCaptcha.value = false
  await doSubmit()
}

async function doSubmit() {
  if (!captchaToken.value) return
  loading.value = true
  const res =
    mode.value === 'login'
      ? await authStore.doLogin(username.value, password.value, captchaToken.value)
      : await authStore.doRegister(
          username.value,
          password.value,
          inviteCode.value.trim(),
          captchaToken.value,
        )
  loading.value = false
  if (res.success) {
    localStorage.setItem('vibebara_user_id', authStore.user?.id || '')
    // 首次登录（未完成引导）→ 进入引导流程；其余直接进主页
    if (authStore.user && !authStore.user.onboarded) {
      router.push('/onboarding')
    } else {
      router.push('/')
    }
  } else {
    toast.error(res.error || (mode.value === 'login' ? '登录失败' : '注册失败'))
    // 验证 token 已被服务端消费（一次性），失败后需重新验证
    captchaToken.value = ''
  }
}
</script>

<template>
  <div class="login-page">
    <img class="page-logo" :src="logoUrl" alt="vibebara" draggable="false" />

    <form class="form" @submit.prevent="handleSubmit">
      <div class="form-head">
        <h2>{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h2>
        <p>
          {{
            mode === 'login'
              ? '登录以继续使用 Vibebara'
              : '测试版需要邀请码，请联系管理员获取'
          }}
        </p>
      </div>

      <div class="flex-column">
        <label for="login-username">用户名</label>
      </div>
      <div class="inputForm">
        <svg height="20" viewBox="0 0 16 16" width="20" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M6 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6m-5 6s-1 0-1-1 1-4 6-4 6 3 6 4-1 1-1 1zM11 3.5a.5.5 0 0 1 .5-.5h4a.5.5 0 0 1 0 1h-4a.5.5 0 0 1-.5-.5m.5 2.5a.5.5 0 0 0 0 1h4a.5.5 0 0 0 0-1zm2 3a.5.5 0 0 0 0 1h2a.5.5 0 0 0 0-1zm0 3a.5.5 0 0 0 0 1h2a.5.5 0 0 0 0-1z"
          ></path>
        </svg>
        <input
          id="login-username"
          v-model="username"
          type="text"
          class="input"
          placeholder="输入用户名"
          autocomplete="username"
          spellcheck="false"
        />
      </div>

      <div class="flex-column">
        <label for="login-password">密码</label>
      </div>
      <div class="inputForm">
        <svg height="20" viewBox="0 0 1024 1024" width="20" xmlns="http://www.w3.org/2000/svg">
          <path
            d="M814.08 366.08h-76.8v-76.8c0-124.416-100.85888-225.28-225.28-225.28s-225.28 100.85888-225.28 225.28v76.8H209.92c-56.55552 0-102.4 45.84448-102.4 102.4v389.12c0 56.55552 45.84448 102.4 102.4 102.4h604.16c56.55552 0 102.4-45.84448 102.4-102.4v-389.12c0-56.55552-45.84448-102.4-102.4-102.4z m-455.68-76.8c0-84.69504 68.90496-153.6 153.6-153.6s153.6 68.90496 153.6 153.6v76.8H358.4v-76.8z m486.4 568.32c0 16.93696-13.77792 30.72-30.72 30.72H209.92c-16.94208 0-30.72-13.78304-30.72-30.72v-389.12c0-16.93696 13.77792-30.72 30.72-30.72h604.16c16.94208 0 30.72 13.78304 30.72 30.72v389.12z"
          ></path>
          <path
            d="M512 550.4a35.84 35.84 0 0 0-35.84 35.84v174.08a35.84 35.84 0 1 0 71.68 0v-174.08a35.84 35.84 0 0 0-35.84-35.84z"
          ></path>
        </svg>
        <input
          id="login-password"
          v-model="password"
          :type="showPassword ? 'text' : 'password'"
          class="input"
          :placeholder="mode === 'register' ? '设置密码' : '输入密码'"
          :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
        />
        <button
          type="button"
          class="toggle-pass"
          :aria-label="showPassword ? '隐藏密码' : '显示密码'"
          @click="showPassword = !showPassword"
        >
          <svg v-if="showPassword" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
            <line x1="3.5" y1="3.5" x2="20.5" y2="20.5" />
          </svg>
          <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
            <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        </button>
      </div>

      <template v-if="mode === 'register'">
        <div class="flex-column">
          <label for="login-confirm">确认密码</label>
        </div>
        <div class="inputForm">
          <svg height="20" viewBox="0 0 1024 1024" width="20" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M814.08 366.08h-76.8v-76.8c0-124.416-100.85888-225.28-225.28-225.28s-225.28 100.85888-225.28 225.28v76.8H209.92c-56.55552 0-102.4 45.84448-102.4 102.4v389.12c0 56.55552 45.84448 102.4 102.4 102.4h604.16c56.55552 0 102.4-45.84448 102.4-102.4v-389.12c0-56.55552-45.84448-102.4-102.4-102.4z m-455.68-76.8c0-84.69504 68.90496-153.6 153.6-153.6s153.6 68.90496 153.6 153.6v76.8H358.4v-76.8z m486.4 568.32c0 16.93696-13.77792 30.72-30.72 30.72H209.92c-16.94208 0-30.72-13.78304-30.72-30.72v-389.12c0-16.93696 13.77792-30.72 30.72-30.72h604.16c16.94208 0 30.72 13.78304 30.72 30.72v389.12z"
            ></path>
            <path
              d="M512 550.4a35.84 35.84 0 0 0-35.84 35.84v174.08a35.84 35.84 0 1 0 71.68 0v-174.08a35.84 35.84 0 0 0-35.84-35.84z"
            ></path>
          </svg>
          <input
            id="login-confirm"
            v-model="confirmPassword"
            :type="showConfirmPassword ? 'text' : 'password'"
            class="input"
            placeholder="再次输入密码"
            autocomplete="new-password"
          />
          <button
            type="button"
            class="toggle-pass"
            :aria-label="showConfirmPassword ? '隐藏密码' : '显示密码'"
            @click="showConfirmPassword = !showConfirmPassword"
          >
            <svg v-if="showConfirmPassword" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
              <line x1="3.5" y1="3.5" x2="20.5" y2="20.5" />
            </svg>
            <svg v-else viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          </button>
        </div>

        <div class="flex-column">
          <label for="login-invite">邀请码</label>
        </div>
        <div class="inputForm">
          <svg height="20" viewBox="0 0 16 16" width="20" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M3.5 11.5a3.5 3.5 0 1 1 3.163-5H14L15.5 8 14 9.5l-1-1-1 1-1-1-1 1-1-1-1 1H6.663a3.5 3.5 0 0 1-3.163 2zM2.5 9a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"
            ></path>
          </svg>
          <input
            id="login-invite"
            v-model="inviteCode"
            type="text"
            class="input"
            placeholder="VH-XXXX-XXXX"
            autocomplete="off"
            spellcheck="false"
          />
        </div>
      </template>

      <button type="submit" class="button-submit" :disabled="loading">
        {{
          loading
            ? mode === 'login' ? '登录中…' : '注册中…'
            : mode === 'login' ? '登 录' : '注 册'
        }}
      </button>

      <p class="p">
        <template v-if="mode === 'login'">
          没有账号？<span class="span" @click="switchMode('register')">使用邀请码注册</span>
        </template>
        <template v-else>
          已有账号？<span class="span" @click="switchMode('login')">直接登录</span>
        </template>
      </p>
    </form>

    <!-- 滑块验证弹窗：点击登录/注册后出现 -->
    <BaseModal v-model="showCaptcha" title="安全验证" :width="360" :body-scroll="false">
      <p class="captcha-sub">拖动滑块完成拼图以继续</p>
      <div class="captcha-slot">
        <SliderCaptcha @verified="onCaptchaVerified" />
      </div>
    </BaseModal>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background-color: #ffffff;
  padding: 24px;
  box-sizing: border-box;
}

.page-logo {
  position: absolute;
  top: 28px;
  left: 32px;
  height: 30px;
}

.form {
  display: flex;
  flex-direction: column;
  gap: 10px;
  background-color: transparent;
  padding: 30px;
  width: 450px;
  max-width: 100%;
  box-sizing: border-box;
  transform: translateY(-40px);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
    Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
}

::placeholder {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen,
    Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
  color: #9ca3af;
}

.form-head {
  text-align: center;
  margin-bottom: 14px;
}

.form-head h2 {
  font-size: 27px;
  font-weight: 650;
  color: #151717;
  margin: 0 0 8px;
}

.form-head p {
  font-size: 15px;
  color: #6b7280;
  margin: 0;
}

.flex-column > label {
  color: #151717;
  font-size: 14px;
  font-weight: 600;
}

.inputForm {
  border: 1.5px solid #ecedec;
  border-radius: 10px;
  height: 50px;
  display: flex;
  align-items: center;
  padding-left: 10px;
  transition: 0.2s ease-in-out;
}

/* 仅作用于输入框左侧的引导图标（锁/用户/钥匙），避免覆盖眼睛线条图标的 fill="none" */
.inputForm > svg {
  flex: 0 0 auto;
  fill: #151717;
}

.input {
  margin-left: 10px;
  border-radius: 10px;
  border: none;
  background: transparent;
  color: #151717;
  font-size: 14.5px;
  flex: 1 1 auto;
  min-width: 0;
  height: 100%;
  padding-right: 10px;
}

.input:focus {
  outline: none;
}

.inputForm:focus-within {
  border: 1.5px solid #2d79f3;
}

.toggle-pass {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 100%;
  padding: 0;
  border: none;
  background: transparent;
  color: #151717;
  cursor: pointer;
  transition: opacity 0.15s ease-in-out;
}

.toggle-pass:hover {
  opacity: 0.6;
}

.error-msg {
  color: #dc2626;
  font-size: 13.5px;
}

.button-submit {
  position: relative;
  overflow: hidden;
  isolation: isolate;
  margin: 20px 0 10px 0;
  background-color: #151717;
  /* 边框始终 #151717：深底态与填充同色（不可见），hover 白底态才显出黑边，故加粗只在白底时生效 */
  border: 2.5px solid #151717;
  color: #ffffff;
  font-size: 15px;
  font-weight: 500;
  letter-spacing: 0.06em;
  border-radius: 10px;
  height: 50px;
  width: 100%;
  cursor: pointer;
  transition: color 0.35s ease;
}

/* 触摸反转：白色从左向右扫入，文字转为深色 */
.button-submit::before {
  content: "";
  position: absolute;
  inset: 0;
  z-index: -1;
  background: #ffffff;
  transform: scaleX(0);
  transform-origin: left center;
  transition: transform 0.35s ease;
}

.button-submit:hover:not(:disabled) {
  color: #151717;
}

.button-submit:hover:not(:disabled)::before {
  transform: scaleX(1);
}

.button-submit:active:not(:disabled) {
  transform: translateY(1px);
}

.button-submit:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.p {
  text-align: center;
  color: black;
  font-size: 14px;
  margin: 5px 0;
}

.span {
  font-size: 14px;
  margin-left: 5px;
  color: #2d79f3;
  font-weight: 500;
  cursor: pointer;
}

.span:hover {
  text-decoration: underline;
}

/* ============ 滑块验证弹窗 ============ */
.captcha-sub {
  font-size: 13px;
  color: #6b7280;
  margin: 0 0 18px;
}

@media (max-width: 520px) {
  .form {
    padding: 24px 20px;
  }

  .page-logo {
    top: 20px;
    left: 20px;
    height: 26px;
  }
}
</style>
