import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  listNativeSkills,
  getNativeSkill,
  createNativeSkill,
  updateNativeSkill,
  deleteNativeSkill,
  importToNativeStore,
  deployNativeSkill,
  previewNativeSkill,
  completeSkillFields,
  testLLMConnection,
  type NativeSkillItem,
  type NativeSkillDetail,
  type PreviewOutput,
  type CompleteFieldsResponse,
  type LLMTestResponse,
} from '@/api/skillStore'
import type { InstalledAtStatus } from '@/api/skillForge'
import { getPlatformInstalledStatus } from '@/api/orchestration'
import { isOrchestrationEnabled } from '@/runtime/config'

export const useSkillStore = defineStore('skill-store', () => {
  const skills = ref<NativeSkillItem[]>([])
  const loading = ref(false)
  const error = ref('')

  const currentId = ref<string | null>(null)
  const currentDetail = ref<NativeSkillDetail | null>(null)
  const currentLoading = ref(false)

  const dirty = ref(false)
  const saving = ref(false)

  const vibehContent = ref('')

  // 决定①：本机平台安装状态（orchestration 形态下由本地代理 scan.installedAt 实时探测，
  // 覆盖云端 deployed_cursor/codex 展示；web 灰度为空表，调用方回退用 deployed_*）。
  const platformInstalled = ref<Record<string, InstalledAtStatus>>({})

  const hasSkills = computed(() => skills.value.length > 0)
  const currentConfig = computed(() => currentDetail.value?.config ?? null)

  /** 某 Skill 是否已装到本机 cursor/codex/windsurf/claude/kiro/trae/qoder/workbuddy：编排形态优先本地代理 scan 结果，否则回退云端字段。 */
  function installedStatus(skill: NativeSkillItem): InstalledAtStatus {
    const local = platformInstalled.value[skill.name]
    if (isOrchestrationEnabled() && local) return local
    return {
      cursor: skill.deployed_cursor,
      codex: skill.deployed_codex,
      windsurf: skill.deployed_windsurf,
      claude: skill.deployed_claude,
      kiro: skill.deployed_kiro,
      trae: skill.deployed_trae,
      qoder: skill.deployed_qoder,
      workbuddy: skill.deployed_workbuddy,
    }
  }

  /** 编排形态下刷新本机平台安装状态（本地代理探测）；非编排形态清空以回退云端字段。 */
  async function refreshPlatformInstalled() {
    if (!isOrchestrationEnabled()) {
      platformInstalled.value = {}
      return
    }
    try {
      platformInstalled.value = await getPlatformInstalledStatus()
    } catch {
      platformInstalled.value = {}
    }
  }

  async function fetchList(scope: 'personal' | 'team' = 'personal') {
    loading.value = true
    error.value = ''
    try {
      const res = await listNativeSkills(scope)
      if (res.success) {
        skills.value = res.skills
      } else {
        error.value = res.error || '获取列表失败'
      }
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e.message || '请求异常'
    } finally {
      loading.value = false
    }
    // 列表就绪后异步刷新本机平台安装状态（不阻塞列表渲染；失败不影响列表）。
    void refreshPlatformInstalled()
  }

  async function selectSkill(id: string) {
    currentId.value = id
    currentLoading.value = true
    dirty.value = false
    try {
      const res = await getNativeSkill(id)
      if (res.success) {
        currentDetail.value = res
        vibehContent.value = res.vibeh_content || ''
      } else {
        currentDetail.value = null
        vibehContent.value = ''
        error.value = res.error || '加载失败'
      }
    } catch (e: any) {
      currentDetail.value = null
      vibehContent.value = ''
      error.value = e.message
    } finally {
      currentLoading.value = false
    }
  }

  function markDirty() {
    dirty.value = true
  }

  function updateLocalConfig(partial: Record<string, unknown>) {
    if (!currentDetail.value) return
    currentDetail.value = {
      ...currentDetail.value,
      config: { ...currentDetail.value.config, ...partial },
    }
    dirty.value = true
  }

  function updateVibeh(content: string) {
    vibehContent.value = content
    dirty.value = true
  }

  async function saveCurrentSkill() {
    if (!currentId.value || !currentDetail.value) return
    saving.value = true
    try {
      const res = await updateNativeSkill(
        currentId.value,
        currentDetail.value.config,
        vibehContent.value || undefined,
      )
      if (res.success) {
        dirty.value = false
        await fetchList()
        if (res.skill) {
          currentDetail.value = {
            ...currentDetail.value,
            db: res.skill,
          }
        }
      } else {
        error.value = res.error || '保存失败'
      }
    } catch (e: any) {
      error.value = e.message
    } finally {
      saving.value = false
    }
  }

  async function createSkill(config: Record<string, unknown>) {
    const res = await createNativeSkill(config)
    if (res.success) {
      await fetchList()
      if (res.skill) {
        await selectSkill(res.skill.id)
      }
    }
    return res
  }

  async function removeSkill(id: string) {
    await deleteNativeSkill(id)
    if (currentId.value === id) {
      currentId.value = null
      currentDetail.value = null
    }
    await fetchList()
  }

  async function importExternal(sourcePath: string, origin?: string) {
    const res = await importToNativeStore(sourcePath, origin)
    if (res.success) {
      await fetchList()
      if (res.skill) {
        await selectSkill(res.skill.id)
      }
    }
    return res
  }

  async function deploy(id: string, target: string, destPath?: string) {
    const res = await deployNativeSkill(id, target, destPath)
    if (res.success) {
      await fetchList()
    }
    return res
  }

  async function preview(id: string, target: string = 'all'): Promise<PreviewOutput[]> {
    const res = await previewNativeSkill(id, target)
    return res.data ?? []
  }

  async function completeFields(id: string): Promise<CompleteFieldsResponse> {
    return await completeSkillFields(id)
  }

  async function testLLM(): Promise<LLMTestResponse> {
    return await testLLMConnection()
  }

  function clearCurrent() {
    currentId.value = null
    currentDetail.value = null
    vibehContent.value = ''
    dirty.value = false
  }

  return {
    skills,
    loading,
    error,
    currentId,
    currentDetail,
    currentLoading,
    dirty,
    saving,
    vibehContent,
    platformInstalled,
    hasSkills,
    currentConfig,
    installedStatus,
    refreshPlatformInstalled,

    fetchList,
    selectSkill,
    markDirty,
    updateLocalConfig,
    updateVibeh,
    saveCurrentSkill,
    createSkill,
    removeSkill,
    importExternal,
    deploy,
    preview,
    completeFields,
    testLLM,
    clearCurrent,
  }
})
