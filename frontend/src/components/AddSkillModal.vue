<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import {
  listNativeSkills,
  copySkillToTeam,
  importLocalSkillToTeam,
  scanLocalSkills,
  scanUrlSkills,
  importUrlSkills,
  createNativeSkill,
  importToNativeStore,
  type NativeSkillItem,
} from '@/api/skillStore'
import { rescanSkills, scanIdeGlobalSkills, type UnifiedSkillPackage, type IdeSkillGroup } from '@/api/skillForge'
import FolderPicker from '@/components/FolderPicker.vue'
import BaseModal from '@/components/BaseModal.vue'
import { toast } from '@/composables/useToast'

// 共享「新建/新增 Skill」模态：个人仓库（SkillForge）与团队仓库（Teams）共用。
// scope='personal'：手动新建 / 从链接导入 / 从本地文件夹 / 从 IDE 工具导入（预留）。
// scope='team'    ：从个人仓库导入 / 从本地文件夹 / 从链接导入（沿用团队既有行为）。
const props = defineProps<{
  modelValue: boolean
  scope: 'personal' | 'team'
  teamId?: string | null
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', val: boolean): void
  // done：有内容真正落库后触发，父组件据此乐观插卡 / 刷新列表 / 弹提示。
  //   - message 非空：完整成功，模态已关闭，父组件可弹成功提示。
  //   - message 为空：部分失败，模态保持打开（内联报错），父组件仅插入已成功的项。
  (e: 'done', payload: { message: string; skills?: NativeSkillItem[] }): void
}>()

type AddMethod = 'manual' | 'personal' | 'local' | 'link' | 'ide'

const methods = computed<{ id: AddMethod; label: string; disabled?: boolean }[]>(() => {
  if (props.scope === 'team') {
    return [
      { id: 'personal', label: '从个人仓库导入' },
      { id: 'local', label: '从本地文件夹' },
      { id: 'link', label: '从链接导入' },
    ]
  }
  return [
    { id: 'manual', label: '手动新建' },
    { id: 'link', label: '从链接导入' },
    { id: 'local', label: '从本地文件夹' },
    { id: 'ide', label: '从 IDE 工具导入' },
  ]
})

const addMethod = ref<AddMethod>('manual')

/** IDE 工具展示名（分组标题 / origin 徽标）。 */
const TOOL_LABELS: Record<IdeSkillGroup['tool'], string> = {
  cursor: 'Cursor',
  codex: 'Codex',
  windsurf: 'Windsurf',
  claude: 'Claude Code',
  kiro: 'Kiro',
  trae: 'Trae',
  qoder: 'Qoder',
  workbuddy: 'WorkBuddy',
}

// —— 手动新建（仅 personal）——
const manualName = ref('')
const manualDesc = ref('')

// —— 从个人仓库导入（仅 team，支持多选）——
const personalSkills = ref<NativeSkillItem[]>([])
const selectedPersonalIds = ref<string[]>([])

// —— 从本地文件夹（两步：解析 → 勾选导入）——
const localPath = ref('')
const scanLoading = ref(false)
const scanned = ref(false)
const scannedPackages = ref<UnifiedSkillPackage[]>([])
const selectedScanPaths = ref<string[]>([])

// —— 从链接导入（两步：解析链接得 token → 勾选导入）——
const linkUrl = ref('')
const urlScanLoading = ref(false)
const urlScanned = ref(false)
const urlToken = ref('')
const urlSourceUrl = ref('')
const urlScannedPackages = ref<UnifiedSkillPackage[]>([])
const selectedUrlPaths = ref<string[]>([])

// —— 从 IDE 工具导入（检索各 IDE 全局目录 → 勾选导入；仅桌面/编排模式）——
const ideScanLoading = ref(false)
const ideScanned = ref(false)
const ideGroups = ref<IdeSkillGroup[]>([])
const selectedIdePaths = ref<string[]>([])
// 当前用户个人仓库已有自然名集合：用于标记「已存在」并默认不勾选。
const personalNameSet = ref<Set<string>>(new Set())
const ideAllPaths = computed(() =>
  ideGroups.value.flatMap((g) => g.packages.map((p) => p.source_path)),
)
function existsInPersonal(p: UnifiedSkillPackage): boolean {
  return personalNameSet.value.has(p.id)
}

const addSkillLoading = ref(false)
// IDE 检索失败标记：用于区分「未发现可导入」与「检索出错」两种空结果。
const ideScanError = ref(false)

function close() {
  emit('update:modelValue', false)
}

function resetLocalScan() {
  scanned.value = false
  scanLoading.value = false
  scannedPackages.value = []
  selectedScanPaths.value = []
}

function resetUrlScan() {
  urlScanned.value = false
  urlScanLoading.value = false
  urlToken.value = ''
  urlSourceUrl.value = ''
  urlScannedPackages.value = []
  selectedUrlPaths.value = []
}

function resetIdeScan() {
  ideScanned.value = false
  ideScanLoading.value = false
  ideGroups.value = []
  selectedIdePaths.value = []
  personalNameSet.value = new Set()
}

function resetAll() {
  manualName.value = ''
  manualDesc.value = ''
  selectedPersonalIds.value = []
  localPath.value = ''
  linkUrl.value = ''
  resetLocalScan()
  resetUrlScan()
  resetIdeScan()
  ideScanError.value = false
  addSkillLoading.value = false
}

// 每次打开重置状态并定位默认方式（team→从个人仓库；personal→手动新建）。
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    resetAll()
    addMethod.value = props.scope === 'team' ? 'personal' : 'manual'
    if (props.scope === 'team') loadPersonalSkills()
  },
)

function switchMethod(m: AddMethod, disabled?: boolean) {
  if (disabled) return
  addMethod.value = m
  // 切到「从 IDE 工具导入」自动检索各 IDE 全局目录（对应「首先检索」）。
  if (m === 'ide' && !ideScanned.value && !ideScanLoading.value) {
    scanIde()
  }
}

// 改变文件夹/链接后需重新解析
watch(localPath, () => {
  if (scanned.value || scannedPackages.value.length) resetLocalScan()
})
watch(linkUrl, () => {
  if (urlScanned.value || urlScannedPackages.value.length) resetUrlScan()
})

async function loadPersonalSkills() {
  try {
    const res = await listNativeSkills('personal')
    personalSkills.value = res.success ? res.skills : []
  } catch {
    personalSkills.value = []
  }
}

/** 完整成功：触发 done（带提示）后关闭模态。 */
function finishDone(message: string, skills?: NativeSkillItem[]) {
  emit('done', { message, skills })
  close()
}

// —— 手动新建 ——
async function confirmManual() {
  const name = manualName.value.trim()
  if (!name) {
    toast.warning('名称不能为空')
    return
  }
  if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) {
    toast.warning('仅支持小写字母、数字、连字符')
    return
  }
  addSkillLoading.value = true
  try {
    const res = await createNativeSkill({
      name,
      description: manualDesc.value.trim() || `Skill: ${name}`,
    })
    if (res.success) {
      finishDone('已创建 Skill', res.skill ? [res.skill] : [])
    } else {
      toast.error(res.error || '创建失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '创建失败')
  } finally {
    addSkillLoading.value = false
  }
}

// —— 从个人仓库导入（team，多选：逐个复制，部分失败保持模态打开并提示）——
async function confirmAddFromPersonal() {
  if (!props.teamId || !selectedPersonalIds.value.length) return
  addSkillLoading.value = true
  let okCount = 0
  const failed: string[] = []
  const imported: NativeSkillItem[] = []
  try {
    for (const id of selectedPersonalIds.value) {
      const s = personalSkills.value.find((p) => p.id === id)
      const res = await copySkillToTeam(props.teamId as string, id)
      if (res.success) {
        okCount += 1
        if (res.skill) imported.push(res.skill)
      } else {
        failed.push(`${s?.display_name || s?.name || s?.id || id}：${res.error || '失败'}`)
      }
    }
    if (failed.length) {
      emit('done', { message: '', skills: imported })
      toast.warning(
        `成功 ${okCount} 个，失败 ${failed.length} 个 — ${failed.join('；')}`,
        5000,
      )
    } else {
      finishDone(`已从个人仓库导入 ${okCount} 个 Skill 到团队仓库`, imported)
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '导入失败')
  } finally {
    addSkillLoading.value = false
  }
}

// —— 从本地文件夹：第一步解析 ——
async function scanLocalFolder() {
  const path = localPath.value.trim()
  if (!path) return
  if (props.scope === 'team' && !props.teamId) return
  scanLoading.value = true
  scannedPackages.value = []
  selectedScanPaths.value = []
  try {
    let ok = false
    let pkgs: UnifiedSkillPackage[] = []
    let err = ''
    if (props.scope === 'team') {
      const res = await scanLocalSkills(props.teamId as string, path)
      ok = res.success
      pkgs = res.packages
      err = res.error || ''
    } else {
      const res = await rescanSkills(path)
      ok = res.status === 'ready'
      pkgs = res.packages
      err = res.error || ''
    }
    if (ok) {
      scannedPackages.value = pkgs
      scanned.value = true
      selectedScanPaths.value = pkgs.map((p) => p.source_path)
    } else {
      toast.error(err || '解析失败')
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '解析失败')
  } finally {
    scanLoading.value = false
  }
}

function toggleScanSelect(path: string) {
  const i = selectedScanPaths.value.indexOf(path)
  if (i >= 0) selectedScanPaths.value.splice(i, 1)
  else selectedScanPaths.value.push(path)
}

// —— 从本地文件夹：第二步导入勾选项 ——
async function confirmAddFromLocal() {
  if (!selectedScanPaths.value.length) return
  if (props.scope === 'team' && !props.teamId) return
  addSkillLoading.value = true
  let okCount = 0
  const failed: string[] = []
  const imported: NativeSkillItem[] = []
  try {
    for (const path of selectedScanPaths.value) {
      const pkg = scannedPackages.value.find((p) => p.source_path === path)
      const res =
        props.scope === 'team'
          ? await importLocalSkillToTeam(props.teamId as string, path, pkg?.origin)
          : await importToNativeStore(path, pkg?.origin)
      if (res.success) {
        okCount += 1
        if (res.skill) imported.push(res.skill)
      } else {
        failed.push(`${pkg?.display_name || pkg?.name || path}：${res.error || '失败'}`)
      }
    }
    if (failed.length) {
      // 部分失败：保持模态打开并以警告弹窗反馈；已成功的项交给父组件乐观插入。
      emit('done', { message: '', skills: imported })
      toast.warning(
        `成功 ${okCount} 个，失败 ${failed.length} 个 — ${failed.join('；')}`,
        5000,
      )
    } else {
      const suffix = props.scope === 'team' ? '到团队仓库' : ''
      finishDone(`已从本地导入 ${okCount} 个 Skill${suffix}`, imported)
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '导入失败')
  } finally {
    addSkillLoading.value = false
  }
}

// —— 从链接导入：第一步解析链接 ——
async function scanLinkUrl() {
  const url = linkUrl.value.trim()
  if (!url) return
  urlScanLoading.value = true
  urlScannedPackages.value = []
  selectedUrlPaths.value = []
  try {
    const res = await scanUrlSkills(url)
    if (res.success) {
      urlToken.value = res.token
      urlSourceUrl.value = res.source_url || url
      urlScannedPackages.value = res.packages
      urlScanned.value = true
      selectedUrlPaths.value = res.packages.map((p) => p.source_path)
      if (!res.packages.length) {
        toast.warning('该链接下未发现可导入的 Skill（需包含 SKILL.md）')
      }
    } else {
      toast.error(res.error || '解析链接失败')
    }
  } catch (e: any) {
    toast.error(
      e?.response?.data?.detail || e?.response?.data?.error || e.message || '解析链接失败',
    )
  } finally {
    urlScanLoading.value = false
  }
}

function toggleUrlSelect(path: string) {
  const i = selectedUrlPaths.value.indexOf(path)
  if (i >= 0) selectedUrlPaths.value.splice(i, 1)
  else selectedUrlPaths.value.push(path)
}

// —— 从链接导入：第二步导入勾选项 ——
async function confirmAddFromUrl() {
  if (!urlToken.value || !selectedUrlPaths.value.length) return
  if (props.scope === 'team' && !props.teamId) return
  addSkillLoading.value = true
  try {
    const res = await importUrlSkills(
      urlToken.value,
      selectedUrlPaths.value,
      props.scope,
      props.scope === 'team' ? (props.teamId as string) : undefined,
      urlSourceUrl.value,
    )
    // token 是一次性的：云端导入后即释放缓存，无论成败都需重新解析才能再次导入。
    urlToken.value = ''
    urlScanned.value = false
    const imported = res.skills || []
    const failed = (res.results || []).filter((r) => !r.success)
    if (failed.length) {
      emit('done', { message: '', skills: imported })
      const detail = failed.map((r) => `${r.source_path}：${r.error || '失败'}`).join('；')
      toast.warning(`成功 ${res.imported} 个，失败 ${failed.length} 个 — ${detail}`, 5000)
    } else {
      const suffix = props.scope === 'team' ? '到团队仓库' : ''
      finishDone(`已从链接导入 ${res.imported} 个 Skill${suffix}`, imported)
    }
  } catch (e: any) {
    toast.error(
      e?.response?.data?.detail || e?.response?.data?.error || e.message || '导入失败',
    )
  } finally {
    addSkillLoading.value = false
  }
}

// —— 从 IDE 工具导入：第一步检索各 IDE 全局目录 ——
async function scanIde() {
  ideScanError.value = false
  ideScanLoading.value = true
  ideScanned.value = false
  ideGroups.value = []
  selectedIdePaths.value = []
  try {
    // 先取当前用户个人仓库已有自然名，用于标记「已存在」并默认跳过。
    try {
      const pres = await listNativeSkills('personal')
      personalNameSet.value = new Set(pres.success ? pres.skills.map((s) => s.name) : [])
    } catch {
      personalNameSet.value = new Set()
    }
    const res = await scanIdeGlobalSkills()
    ideScanned.value = true
    if (res.success) {
      ideGroups.value = res.groups
      // 默认仅勾选个人仓库中尚不存在的项；已存在项默认不勾选（用户可勾选以覆盖）。
      selectedIdePaths.value = res.groups.flatMap((g) =>
        g.packages.filter((p) => !existsInPersonal(p)).map((p) => p.source_path),
      )
    } else {
      ideScanError.value = true
      toast.error(res.error || '检索失败')
    }
  } catch (e: any) {
    ideScanned.value = true
    ideScanError.value = true
    toast.error(e?.response?.data?.detail || e.message || '检索失败')
  } finally {
    ideScanLoading.value = false
  }
}

function toggleIdeSelect(path: string) {
  const i = selectedIdePaths.value.indexOf(path)
  if (i >= 0) selectedIdePaths.value.splice(i, 1)
  else selectedIdePaths.value.push(path)
}

// —— 从 IDE 工具导入：第二步顺序导入勾选项（origin=所属 IDE）——
async function confirmAddFromIde() {
  if (!selectedIdePaths.value.length) return
  addSkillLoading.value = true
  let okCount = 0
  const failed: string[] = []
  const imported: NativeSkillItem[] = []
  try {
    // 按分组顺序逐个导入，与本地/链接 tab 体验一致。
    for (const group of ideGroups.value) {
      for (const pkg of group.packages) {
        if (!selectedIdePaths.value.includes(pkg.source_path)) continue
        const res = await importToNativeStore(pkg.source_path, group.tool)
        if (res.success) {
          okCount += 1
          if (res.skill) imported.push(res.skill)
        } else {
          failed.push(`${pkg.display_name || pkg.name || pkg.source_path}：${res.error || '失败'}`)
        }
      }
    }
    if (failed.length) {
      emit('done', { message: '', skills: imported })
      toast.warning(`成功 ${okCount} 个，失败 ${failed.length} 个 — ${failed.join('；')}`, 5000)
    } else {
      finishDone(`已从 IDE 导入 ${okCount} 个 Skill`, imported)
    }
  } catch (e: any) {
    toast.error(e?.response?.data?.detail || e.message || '导入失败')
  } finally {
    addSkillLoading.value = false
  }
}
</script>

<template>
  <BaseModal
    :model-value="modelValue"
    :title="scope === 'team' ? '新增 Skill' : '新建 Skill'"
    :width="520"
    @update:model-value="emit('update:modelValue', $event)"
  >
        <div class="method-tabs">
          <button
            v-for="m in methods"
            :key="m.id"
            class="method-tab"
            :class="{ active: addMethod === m.id, disabled: m.disabled }"
            @click="switchMethod(m.id, m.disabled)"
          >
            {{ m.label }}
          </button>
        </div>

        <!-- 手动新建（personal） -->
        <div v-if="addMethod === 'manual'" class="method-body">
          <p class="hint">填写名称与描述创建一个空白 Skill，随后在编辑器中编写指令与资源。</p>
          <div class="field">
            <label>名称 (ID)</label>
            <input
              v-model="manualName"
              placeholder="my-awesome-skill"
              @keyup.enter="confirmManual"
            />
          </div>
          <div class="field">
            <label>描述</label>
            <input
              v-model="manualDesc"
              placeholder="一句话描述该 Skill"
              @keyup.enter="confirmManual"
            />
          </div>
          <p class="hint">ID 仅支持小写字母、数字、连字符。</p>
        </div>

        <!-- 从个人仓库导入（team，多选） -->
        <div v-else-if="addMethod === 'personal'" class="method-body">
          <p class="hint">选择你个人仓库中的 Skill（可多选），各复制一份放入当前团队仓库。</p>
          <div v-if="personalSkills.length" class="personal-list">
            <label
              v-for="s in personalSkills"
              :key="s.id"
              class="personal-item"
              :class="{ selected: selectedPersonalIds.includes(s.id) }"
            >
              <input
                type="checkbox"
                :value="s.id"
                v-model="selectedPersonalIds"
              />
              <span class="pi-main">
                <span class="pi-name">{{ s.display_name || s.name || s.id }}</span>
                <span class="pi-desc">{{ s.description || '暂无描述' }}</span>
              </span>
            </label>
          </div>
          <div v-else class="empty-hint" style="margin-top: 12px">个人仓库暂无 Skill</div>
        </div>

        <!-- 从本地文件夹（两步） -->
        <div v-else-if="addMethod === 'local'" class="method-body">
          <p class="hint">
            第一步：选择本地文件夹并解析；第二步：勾选解析出的 Skill 导入。
          </p>
          <FolderPicker v-model="localPath" placeholder="点击「浏览...」选择文件夹" />

          <div v-if="scanned" class="scan-result">
            <div class="scan-result-head">
              解析到 {{ scannedPackages.length }} 个 Skill
              <button
                v-if="scannedPackages.length"
                class="link-btn"
                @click="
                  selectedScanPaths =
                    selectedScanPaths.length === scannedPackages.length
                      ? []
                      : scannedPackages.map((p) => p.source_path)
                "
              >
                {{ selectedScanPaths.length === scannedPackages.length ? '取消全选' : '全选' }}
              </button>
            </div>
            <div v-if="scannedPackages.length" class="scan-list">
              <label
                v-for="p in scannedPackages"
                :key="p.source_path"
                class="scan-item"
                :class="{ selected: selectedScanPaths.includes(p.source_path) }"
              >
                <input
                  type="checkbox"
                  :checked="selectedScanPaths.includes(p.source_path)"
                  @change="toggleScanSelect(p.source_path)"
                />
                <span class="pi-main">
                  <span class="pi-name">
                    {{ p.display_name || p.name }}
                    <span class="origin-badge">{{ p.origin }}</span>
                  </span>
                  <span class="pi-desc">{{ p.description || p.short_description || '暂无描述' }}</span>
                  <span class="pi-path">{{ p.source_path }}</span>
                </span>
              </label>
            </div>
            <div v-else class="empty-hint" style="margin-top: 12px">
              该文件夹下未发现可导入的 Skill（需包含 SKILL.md）
            </div>
          </div>
        </div>

        <!-- 从链接导入（两步） -->
        <div v-else-if="addMethod === 'link'" class="method-body">
          <p class="hint">
            粘贴一个链接（GitHub / Gitee / GitLab 仓库，或 .zip / .tar.gz 归档），
            自动解析其中的 Skill 后勾选导入。
          </p>
          <div class="url-input-row">
            <input
              v-model="linkUrl"
              class="url-input"
              placeholder="如 https://github.com/owner/repo 或 .../tree/main/skills/foo"
              :disabled="urlScanLoading"
              @keyup.enter="scanLinkUrl"
            />
          </div>

          <div v-if="urlScanned" class="scan-result">
            <div class="scan-result-head">
              解析到 {{ urlScannedPackages.length }} 个 Skill
              <button
                v-if="urlScannedPackages.length"
                class="link-btn"
                @click="
                  selectedUrlPaths =
                    selectedUrlPaths.length === urlScannedPackages.length
                      ? []
                      : urlScannedPackages.map((p) => p.source_path)
                "
              >
                {{ selectedUrlPaths.length === urlScannedPackages.length ? '取消全选' : '全选' }}
              </button>
            </div>
            <div v-if="urlScannedPackages.length" class="scan-list">
              <label
                v-for="p in urlScannedPackages"
                :key="p.source_path"
                class="scan-item"
                :class="{ selected: selectedUrlPaths.includes(p.source_path) }"
              >
                <input
                  type="checkbox"
                  :checked="selectedUrlPaths.includes(p.source_path)"
                  @change="toggleUrlSelect(p.source_path)"
                />
                <span class="pi-main">
                  <span class="pi-name">
                    {{ p.display_name || p.name }}
                    <span class="origin-badge">{{ p.origin }}</span>
                  </span>
                  <span class="pi-desc">{{ p.description || p.short_description || '暂无描述' }}</span>
                  <span class="pi-path">{{ p.source_path === '.' ? '（仓库根目录）' : p.source_path }}</span>
                </span>
              </label>
            </div>
            <div v-else class="empty-hint" style="margin-top: 12px">
              该链接下未发现可导入的 Skill（需包含 SKILL.md）
            </div>
          </div>
        </div>

        <!-- 从 IDE 工具导入：检索各 IDE 全局目录 → 勾选导入 -->
        <div v-else-if="addMethod === 'ide'" class="method-body">
          <p class="hint">
            从本机已安装的 IDE（Cursor / Codex 等）全局 Skill 目录检索，勾选后以快照导入到个人仓库（不跟踪）。
            个人仓库已有同名的标记为「已存在」，默认不勾选——勾选则覆盖；团队仓库同名的会作为独立副本导入。
          </p>

          <div v-if="ideScanLoading" class="ide-loading">
            <span class="spinner-sm"></span> 正在检索各 IDE 全局目录...
          </div>

          <div v-else-if="ideScanned" class="scan-result">
            <div class="scan-result-head">
              共检索到 {{ ideAllPaths.length }} 个 Skill（{{ ideGroups.length }} 个 IDE）
              <button
                v-if="ideAllPaths.length"
                class="link-btn"
                @click="
                  selectedIdePaths =
                    selectedIdePaths.length === ideAllPaths.length ? [] : [...ideAllPaths]
                "
              >
                {{ selectedIdePaths.length === ideAllPaths.length ? '取消全选' : '全选' }}
              </button>
            </div>

            <div v-if="ideGroups.length" class="ide-groups">
              <div v-for="g in ideGroups" :key="g.tool" class="ide-group">
                <div class="ide-group-head">
                  <span class="ide-group-name">{{ TOOL_LABELS[g.tool] }}</span>
                  <span class="ide-group-count">{{ g.packages.length }}</span>
                </div>
                <div class="scan-list">
                  <label
                    v-for="p in g.packages"
                    :key="p.source_path"
                    class="scan-item"
                    :class="{ selected: selectedIdePaths.includes(p.source_path) }"
                  >
                    <input
                      type="checkbox"
                      :checked="selectedIdePaths.includes(p.source_path)"
                      @change="toggleIdeSelect(p.source_path)"
                    />
                    <span class="pi-main">
                      <span class="pi-name">
                        {{ p.display_name || p.name }}
                        <span class="origin-badge">{{ TOOL_LABELS[g.tool] }}</span>
                        <span v-if="existsInPersonal(p)" class="exists-badge" title="个人仓库已存在同名 Skill，勾选将覆盖">已存在 · 勾选将覆盖</span>
                      </span>
                      <span class="pi-desc">{{ p.description || p.short_description || '暂无描述' }}</span>
                      <span class="pi-path">{{ p.source_path }}</span>
                    </span>
                  </label>
                </div>
              </div>
            </div>
            <div v-else-if="!ideScanError" class="empty-hint" style="margin-top: 12px">
              未在本机各 IDE 全局目录发现可导入的 Skill（需包含 SKILL.md）
            </div>
          </div>
        </div>

        <template #footer>
          <button
            v-if="addMethod === 'manual'"
            class="btn-sm btn-primary"
            :disabled="!manualName.trim() || addSkillLoading"
            @click="confirmManual"
          >
            {{ addSkillLoading ? '创建中...' : '创建' }}
          </button>

          <button
            v-else-if="addMethod === 'personal'"
            class="btn-sm btn-primary"
            :disabled="!selectedPersonalIds.length || addSkillLoading"
            @click="confirmAddFromPersonal"
          >
            {{
              addSkillLoading
                ? '导入中...'
                : selectedPersonalIds.length > 1
                  ? `导入到团队 (${selectedPersonalIds.length})`
                  : '导入到团队'
            }}
          </button>

          <template v-else-if="addMethod === 'local'">
            <button
              v-if="!scanned"
              class="btn-sm btn-primary"
              :disabled="!localPath.trim() || scanLoading"
              @click="scanLocalFolder"
            >
              {{ scanLoading ? '解析中...' : '解析文件夹' }}
            </button>
            <button
              v-else
              class="btn-sm btn-primary"
              :disabled="!selectedScanPaths.length || addSkillLoading"
              @click="confirmAddFromLocal"
            >
              {{ addSkillLoading ? '导入中...' : `导入所选 (${selectedScanPaths.length})` }}
            </button>
          </template>

          <template v-else-if="addMethod === 'link'">
            <button
              v-if="!urlScanned"
              class="btn-sm btn-primary"
              :disabled="!linkUrl.trim() || urlScanLoading"
              @click="scanLinkUrl"
            >
              {{ urlScanLoading ? '解析中...' : '解析链接' }}
            </button>
            <button
              v-else
              class="btn-sm btn-primary"
              :disabled="!selectedUrlPaths.length || addSkillLoading"
              @click="confirmAddFromUrl"
            >
              {{ addSkillLoading ? '导入中...' : `导入所选 (${selectedUrlPaths.length})` }}
            </button>
          </template>

          <template v-else-if="addMethod === 'ide'">
            <button
              v-if="!ideScanned && !ideScanLoading"
              class="btn-sm btn-primary"
              @click="scanIde"
            >
              检索 IDE 目录
            </button>
            <button
              v-else
              class="btn-sm btn-primary"
              :disabled="!selectedIdePaths.length || addSkillLoading || ideScanLoading"
              @click="confirmAddFromIde"
            >
              {{ addSkillLoading ? '导入中...' : `导入所选 (${selectedIdePaths.length})` }}
            </button>
          </template>
        </template>
  </BaseModal>
</template>

<style scoped>
.method-tabs {
  display: flex;
  gap: 6px;
  margin-bottom: 16px;
  flex-shrink: 0;
}

.method-tab {
  flex: 1;
  padding: 8px 4px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #ffffff;
  color: #6b7280;
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  white-space: nowrap;
  transition: border-color 0.15s ease, background 0.15s ease, color 0.15s ease;
}

.method-tab:hover:not(.disabled):not(.active) {
  color: #151717;
}

.method-tab.active {
  border-color: #151717;
  background: #151717;
  color: #ffffff;
  font-weight: 600;
}

.method-tab.disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.method-body {
  min-height: 80px;
  /* grow=0：内容少时模态贴合内容；内容多到触顶 max-height 时本区域收缩并出现唯一滚动条 */
  flex: 0 1 auto;
  overflow-y: auto;
  /* 给滚动条留出与内容的间距，避免滑块压住卡片右边框 */
  margin-right: -8px;
  padding-right: 8px;
}

.hint {
  font-size: 13px;
  color: #9ca3af;
  line-height: 1.6;
  margin: 0 0 12px;
}

.field {
  margin-bottom: 16px;
}

.field label {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #6b7280;
  margin-bottom: 6px;
}

.field input {
  width: 100%;
  padding: 10px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  background: #f6f7f8;
  color: #151717;
  font-size: 14px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.field input::placeholder {
  color: #b6bcc4;
}

.field input:focus {
  border-color: #151717;
  background: #ffffff;
}

.personal-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.personal-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 2px solid #ebedf0;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.personal-item:hover {
  background: #f6f7f8;
}

.personal-item.selected {
  border-color: #151717;
  background: #f6f7f8;
}

.personal-item input {
  margin-top: 3px;
  accent-color: #151717;
}

.pi-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.pi-name {
  font-size: 14px;
  font-weight: 500;
  color: #151717;
}

.pi-desc {
  font-size: 12px;
  color: #6b7280;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  line-clamp: 1;
  -webkit-box-orient: vertical;
}

.scan-result {
  margin-top: 14px;
}

.scan-result-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #6b7280;
  margin-bottom: 8px;
}

.link-btn {
  background: none;
  border: none;
  color: #4f46e5;
  font-size: 12px;
  font-weight: 600;
  font-family: inherit;
  cursor: pointer;
  padding: 0;
}

.link-btn:hover {
  text-decoration: underline;
}

.scan-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.scan-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 12px;
  border: 2px solid #ebedf0;
  border-radius: 10px;
  cursor: pointer;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.scan-item:hover {
  background: #f6f7f8;
}

.scan-item.selected {
  border-color: #151717;
  background: #f6f7f8;
}

.scan-item input {
  margin-top: 3px;
  accent-color: #151717;
}

.origin-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #4b5563;
  font-size: 11px;
  vertical-align: middle;
}

.exists-badge {
  display: inline-block;
  margin-left: 6px;
  padding: 0 6px;
  border-radius: 999px;
  background: #fffbeb;
  color: #b45309;
  font-size: 11px;
  vertical-align: middle;
}

.pi-path {
  font-size: 11px;
  color: #9ca3af;
  font-family: 'JetBrains Mono', monospace;
  word-break: break-all;
}

/* —— 从 IDE 工具导入 —— */
.ide-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 14px;
  font-size: 13px;
  color: #6b7280;
}

.ide-groups {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.ide-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ide-group-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #151717;
  padding: 2px 0;
  border-bottom: 1px solid #f3f4f6;
}

.ide-group-name {
  letter-spacing: 0.02em;
}

.ide-group-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 16px;
  padding: 0 5px;
  border-radius: 999px;
  background: #f3f4f6;
  color: #6b7280;
  font-size: 11px;
  font-weight: 600;
}

.spinner-sm {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #e5e7eb;
  border-top-color: #151717;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.url-input-row {
  display: flex;
  gap: 8px;
}

.url-input {
  flex: 1;
  padding: 9px 12px;
  border: 2px solid #e5e7eb;
  border-radius: 8px;
  background: #f6f7f8;
  color: #151717;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.15s ease, background 0.15s ease;
}

.url-input:focus {
  border-color: #151717;
  background: #ffffff;
}

.url-input::placeholder {
  color: #b6bcc4;
}

.url-input:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.empty-hint {
  text-align: center;
  color: #9ca3af;
  font-size: 13px;
}

.btn-sm {
  padding: 7px 14px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  color: #6b7280;
  font-size: 13px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.btn-sm:hover:not(:disabled) {
  border-color: #d1d5db;
  color: #151717;
}

.btn-sm:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn-primary {
  background: #151717;
  border-color: #151717;
  color: #ffffff;
  font-weight: 600;
}

.btn-primary:hover:not(:disabled) {
  background: #2d2f2f;
  border-color: #2d2f2f;
  color: #ffffff;
}
</style>
