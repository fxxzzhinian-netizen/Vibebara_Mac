import apiClient from './client'
import type { ChangeItem } from './projects'
import type { UnifiedSkillPackage } from './skillForge'
import { normalizeScanPackage } from './skillForge'
import { isOrchestrationEnabled } from '@/runtime/config'
import { DEV_SKIP_AUTH } from '@/runtime/devAuth'
import { devMockSkillList, devMockSkillDetail } from '@/runtime/devMock'
import * as localAgent from './localAgent'
import {
  deployNativeSkillOrchestrated,
  importContentOrchestrated,
} from './orchestration'

export interface NativeSkillItem {
  id: string
  // 自然名用于展示与本机部署目录；id 是个人 UUID / 团队代理键。
  name: string
  display_name: string
  description: string
  short_description: string
  version: string
  tags: string[]
  imported_from: string | null
  store_path: string
  scope: string
  team_id: string | null
  owner_id: string | null
  source_skill_id: string | null
  content_hash: string
  deployed_cursor: boolean
  deployed_codex: boolean
  deployed_windsurf: boolean
  deployed_claude: boolean
  deployed_kiro: boolean
  deployed_trae: boolean
  deployed_qoder: boolean
  deployed_workbuddy: boolean
  created_at: string | null
  updated_at: string | null
}

export interface NativeSkillDetail {
  success: boolean
  id: string
  config: Record<string, unknown>
  vibeh_content: string
  store_path: string
  db: NativeSkillItem | null
  error?: string
}

export interface CompleteFieldsResponse {
  success: boolean
  incomplete_fields: string[]
  suggestions: Record<string, string>
  error?: string
}

export interface LLMTestResponse {
  success: boolean
  model?: string
  base_url?: string
  response?: string
  usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number }
  error?: string
}

export interface NativeSkillListResponse {
  success: boolean
  skills: NativeSkillItem[]
  error?: string
}

export interface SkillVersionItem {
  id: string
  skill_id: string
  team_id: string | null
  seq: number
  version_number: string
  label: string
  content_hash: string
  change_summary: string
  change_items: ChangeItem[]
  resource_count: number
  source: string
  created_by: string
  created_by_name: string
  created_at: string | null
}

export interface SkillVersionDetail extends SkillVersionItem {
  config: Record<string, unknown>
  vibeh_content: string
  resources: string[]
}

export interface MutationResponse {
  success: boolean
  skill?: NativeSkillItem
  error?: string
  no_change?: boolean
  diff_summary?: string
  change_items?: ChangeItem[]
  version?: SkillVersionItem | null
}

export interface DeployResponse {
  success: boolean
  deployed: { target: string; path: string }[]
  error?: string
}

export interface PreviewOutput {
  target: string
  contents: Record<string, string>
}

export interface PreviewResponse {
  success: boolean
  data?: PreviewOutput[]
  error?: string
}

export async function listNativeSkills(
  scope: 'personal' | 'team' = 'personal',
): Promise<NativeSkillListResponse> {
  // 开发者模式（跳过登录）下后端会因假 token 返回 401，这里直接回放假数据预览样式。
  if (DEV_SKIP_AUTH) return devMockSkillList(scope)
  const { data } = await apiClient.get<NativeSkillListResponse>(
    '/skill-forge/store/list',
    { params: { scope } },
  )
  return data
}

export async function getNativeSkill(id: string): Promise<NativeSkillDetail> {
  if (DEV_SKIP_AUTH) return devMockSkillDetail(id)
  const { data } = await apiClient.get<NativeSkillDetail>(
    `/skill-forge/store/${id}`,
  )
  return data
}

export async function createNativeSkill(
  config: Record<string, unknown>,
  vibeh_content?: string,
): Promise<MutationResponse> {
  const { data } = await apiClient.post<MutationResponse>(
    '/skill-forge/store/create',
    { config, vibeh_content: vibeh_content ?? null },
  )
  return data
}

export async function updateNativeSkill(
  id: string,
  partial: Record<string, unknown>,
  vibeh_content?: string,
  opts?: { createVersion?: boolean; versionNumber?: string; versionLabel?: string },
): Promise<MutationResponse> {
  const { data } = await apiClient.put<MutationResponse>(
    `/skill-forge/store/${id}`,
    {
      partial,
      vibeh_content: vibeh_content ?? null,
      create_version: opts?.createVersion ?? false,
      version_number: opts?.versionNumber ?? '',
      version_label: opts?.versionLabel ?? '',
    },
  )
  return data
}

// ---- 单个资源文件读写（scripts/references/assets 文件树编辑器） ----
export interface ResourceFileContent {
  success: boolean
  path: string
  encoding: 'utf8' | 'base64'
  content: string
  size: number
  is_binary: boolean
  error?: string
}

export interface ResourceFileWriteResult {
  success: boolean
  path?: string
  content_hash?: string
  error?: string
}

/** 读取单个资源文件真实内容（从对象存储/COS）。 */
export async function readResourceFile(
  skillId: string,
  path: string,
): Promise<ResourceFileContent> {
  const { data } = await apiClient.get<ResourceFileContent>(
    `/skill-forge/store/${skillId}/resource-file`,
    { params: { path } },
  )
  return data
}

/** 保存单个资源文件内容（写回对象存储/COS）。 */
export async function writeResourceFile(
  skillId: string,
  path: string,
  content: string,
  encoding: 'utf8' | 'base64' = 'utf8',
): Promise<ResourceFileWriteResult> {
  const { data } = await apiClient.put<ResourceFileWriteResult>(
    `/skill-forge/store/${skillId}/resource-file`,
    { path, content, encoding },
  )
  return data
}

export interface SkillVersionListResponse {
  success: boolean
  versions: SkillVersionItem[]
  error?: string
}

export interface SkillVersionDetailResponse {
  success: boolean
  version?: SkillVersionDetail
  error?: string
}

export interface RestoreVersionResponse {
  success: boolean
  version?: SkillVersionItem
  diff_summary?: string
  error?: string
}

export async function listSkillVersions(
  skillId: string,
): Promise<SkillVersionListResponse> {
  const { data } = await apiClient.get<SkillVersionListResponse>(
    `/skill-forge/store/${skillId}/versions`,
  )
  return data
}

export async function getSkillVersion(
  skillId: string,
  versionId: string,
): Promise<SkillVersionDetailResponse> {
  const { data } = await apiClient.get<SkillVersionDetailResponse>(
    `/skill-forge/store/${skillId}/versions/${versionId}`,
  )
  return data
}

/** 版本快照中某个资源文件的一侧内容（新/旧）。 */
export interface VersionResourceFileSide {
  exists: boolean
  encoding: 'utf8' | 'base64' | 'none'
  content: string
  size: number
  is_binary: boolean
  too_large: boolean
}

export interface VersionResourceFileResponse {
  success: boolean
  path?: string
  change?: 'added' | 'removed' | 'modified' | 'unknown'
  seq?: number
  version_number?: string
  prev_version_id?: string | null
  prev_seq?: number | null
  prev_version_number?: string | null
  new?: VersionResourceFileSide | null
  old?: VersionResourceFileSide | null
  diff?: string
  diff_truncated?: boolean
  error?: string
}

/** 读取某版本快照里单个资源文件的内容，并附带与上一版本的 unified diff。 */
export async function readVersionResourceFile(
  skillId: string,
  versionId: string,
  path: string,
): Promise<VersionResourceFileResponse> {
  const { data } = await apiClient.get<VersionResourceFileResponse>(
    `/skill-forge/store/${skillId}/versions/${versionId}/resource-file`,
    { params: { path } },
  )
  return data
}

export async function restoreSkillVersion(
  skillId: string,
  versionId: string,
): Promise<RestoreVersionResponse> {
  const { data } = await apiClient.post<RestoreVersionResponse>(
    `/skill-forge/store/${skillId}/versions/${versionId}/restore`,
  )
  return data
}

export async function completeSkillFields(
  id: string,
): Promise<CompleteFieldsResponse> {
  const { data } = await apiClient.post<CompleteFieldsResponse>(
    `/skill-forge/store/${id}/complete`,
  )
  return data
}

export async function testLLMConnection(): Promise<LLMTestResponse> {
  const { data } = await apiClient.get<LLMTestResponse>(
    '/skill-forge/store/llm/test',
  )
  return data
}

/** AI 辅助生成的「介绍页」草稿。 */
export interface SkillIntroDraft {
  title: string
  category: string
  short_description: string
  intro_md: string
}

export interface SkillIntroDraftResponse {
  success: boolean
  draft?: SkillIntroDraft
  error?: string
}

/** 「介绍」面板「AI 辅助生成」：根据 Skill 内容生成介绍草稿（不落库）。 */
export async function generateSkillIntroDraft(
  skillId: string,
): Promise<SkillIntroDraftResponse> {
  const { data } = await apiClient.post<SkillIntroDraftResponse>(
    `/skill-forge/store/${skillId}/intro/generate`,
  )
  return data
}

export async function deleteNativeSkill(id: string): Promise<{ success: boolean }> {
  const { data } = await apiClient.delete<{ success: boolean }>(
    `/skill-forge/store/${id}`,
  )
  return data
}

export async function importToNativeStore(
  sourcePath: string,
  origin?: string,
): Promise<MutationResponse> {
  // 灰度分流：编排开启 → 本地代理 read-folder → 云端 import-content（M0 §3.5）；
  // 否则走旧的一次性云端 /skill-forge/store/import。
  if (isOrchestrationEnabled()) {
    return importContentOrchestrated(sourcePath, origin, 'personal')
  }
  const { data } = await apiClient.post<MutationResponse>(
    '/skill-forge/store/import',
    { source_path: sourcePath, origin: origin ?? null },
  )
  return data
}

export async function deployNativeSkill(
  id: string,
  target: string,
  destPath?: string,
): Promise<DeployResponse> {
  // 开发者环境：个人仓库为 mock 数据，云端 / 本地代理并无对应 Skill，直接返回成功，
  // 便于预览部署后的流程（如「是否打开 XXX」弹窗）。
  if (DEV_SKIP_AUTH) {
    const base = (destPath || '').replace(/[\\/]+$/, '')
    const path = base
      ? `${base}\\.${target}\\skills\\${id}`
      : `~/.${target}/skills/${id}`
    return { success: true, deployed: [{ target, path }] }
  }
  // 灰度分流：编排开启 → 云端产物 → 本地代理 write-skill 落盘（M0 §3.1 变体）；
  // 否则走旧的一次性云端 /skill-forge/store/{id}/deploy。
  if (isOrchestrationEnabled()) {
    return deployNativeSkillOrchestrated(id, target, destPath)
  }
  const { data } = await apiClient.post<DeployResponse>(
    `/skill-forge/store/${id}/deploy`,
    { target, dest_path: destPath ?? null },
  )
  return data
}

export async function previewNativeSkill(
  id: string,
  target: string = 'all',
): Promise<PreviewResponse> {
  const { data } = await apiClient.get<PreviewResponse>(
    `/skill-forge/store/${id}/preview`,
    { params: { target } },
  )
  return data
}

export async function copySkillToTeam(
  teamId: string,
  skillId: string,
): Promise<MutationResponse> {
  const { data } = await apiClient.post<MutationResponse>(
    `/teams/${teamId}/skills/from-personal/${skillId}`,
  )
  return data
}

export interface TeamSkillScanResponse {
  success: boolean
  packages: UnifiedSkillPackage[]
  error?: string
}

export async function scanLocalSkills(
  teamId: string,
  path: string,
): Promise<TeamSkillScanResponse> {
  // 灰度分流：编排开启 → 本地代理 POST /local/scan；否则走旧的云端 scan-local。
  if (isOrchestrationEnabled()) {
    try {
      const res = await localAgent.scan({ rootDir: path })
      return { success: res.status === 'ready', packages: res.packages.map(normalizeScanPackage), error: res.scanError ?? undefined }
    } catch (e) {
      const err = e as { message?: string }
      return { success: false, packages: [], error: err?.message || '本地代理扫描失败' }
    }
  }
  const { data } = await apiClient.post<TeamSkillScanResponse>(
    `/teams/${teamId}/skills/scan-local`,
    { path },
  )
  return data
}

export async function importLocalSkillToTeam(
  teamId: string,
  sourcePath: string,
  origin?: string,
): Promise<MutationResponse> {
  // 灰度分流：编排开启 → 本地代理 read-folder → 云端 import-content(scope=team)（M0 §3.5）；
  // 否则走旧的一次性云端 import-local。
  if (isOrchestrationEnabled()) {
    return importContentOrchestrated(sourcePath, origin, 'team', teamId)
  }
  const { data } = await apiClient.post<MutationResponse>(
    `/teams/${teamId}/skills/import-local`,
    { source_path: sourcePath, origin: origin ?? null },
  )
  return data
}

// =========================================================================
// 从远程链接导入 Skill（GitHub/Gitee/GitLab 仓库或归档 URL）
//
// 全局可复用：个人与团队仓库共用同一套云端解析/导入端点，仅 scope/teamId 不同。
// 该流程「下载源 + 解析 + 落库」全部在云端完成（与本地文件夹导入不同，不依赖本地
// 代理），因此**不走 orchestration 分流**，始终调用云端 apiClient。
// =========================================================================

export interface UrlSkillScanResponse {
  success: boolean
  token: string
  packages: UnifiedSkillPackage[]
  source_url: string
  error?: string
}

export interface UrlImportResultItem {
  source_path: string
  success: boolean
  skill?: NativeSkillItem
  error?: string
}

export interface UrlImportResponse {
  success: boolean
  imported: number
  skills: NativeSkillItem[]
  results: UrlImportResultItem[]
  error?: string
}

// 链接导入由云端下载 + 解压整个仓库后再解析，耗时远超普通接口（尤其国内服务器
// 拉取 github.com 可能较慢），需放宽 axios 默认 15s 超时，否则请求未完成即被前端中断。
const URL_SCAN_TIMEOUT_MS = 180000
const URL_IMPORT_TIMEOUT_MS = 180000

/** 第一步：解析链接，返回缓存 token 与发现的可导入 Skill 列表。 */
export async function scanUrlSkills(url: string): Promise<UrlSkillScanResponse> {
  const { data } = await apiClient.post<UrlSkillScanResponse>(
    '/skill-forge/store/import-url/scan',
    { url },
    { timeout: URL_SCAN_TIMEOUT_MS },
  )
  return data
}

/**
 * 第二步：把勾选的 Skill 导入到个人 / 团队仓库。
 * scope='team' 时需传 teamId；sourceUrl 仅用于溯源记录。
 */
export async function importUrlSkills(
  token: string,
  sourcePaths: string[],
  scope: 'personal' | 'team' = 'personal',
  teamId?: string,
  sourceUrl?: string,
): Promise<UrlImportResponse> {
  const { data } = await apiClient.post<UrlImportResponse>(
    '/skill-forge/store/import-url',
    {
      token,
      source_paths: sourcePaths,
      scope,
      teamId: teamId ?? null,
      sourceUrl: sourceUrl ?? null,
    },
    { timeout: URL_IMPORT_TIMEOUT_MS },
  )
  return data
}
