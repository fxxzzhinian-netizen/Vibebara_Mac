import apiClient from './client'
import { isOrchestrationEnabled } from '@/runtime/config'
import { DEV_SKIP_AUTH } from '@/runtime/devAuth'
import {
  devMockProjectList,
  devMockProjectDetail,
  devMockUpdateProject,
} from '@/runtime/devMock'
import {
  deployProjectSkillOrchestrated,
  deployProjectSkillGlobalOrchestrated,
  pushOrchestrated,
  pullUpdateOrchestrated,
  getLocalStatusOrchestrated,
  resumeTrackingOrchestrated,
  mergePreviewOrchestrated,
  mergeCommitOrchestrated,
} from './orchestration'
import type {
  MergePreviewResponse,
  MergedContent,
  MergeCommitResult,
} from './orchestration'

export type { MergePreviewResponse, MergedContent, MergeCommitResult, MergeResourceOp, MergeManualConflict } from './orchestration'

export interface ProjectInfo {
  id: string
  team_id: string
  name: string
  description: string
  created_by: string
  skill_count: number
  // 当前用户在该项目下本地有改动待推送的 Skill 数（待提交）
  pending_commit_count: number
  // 当前用户在该项目下团队仓库有新版本可拉取的 Skill 数（待更新）
  pending_update_count: number
  // 该项目最近一次推送到团队仓库（提交）的时间
  last_commit_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ProjectSkillInfo {
  skill_id: string
  display_name: string
  description: string
  version: number
  content_hash: string
  last_modified_by: string
  updated_at: string | null
  deployment: UserSkillDeploymentInfo | null
}

export interface UserSkillDeploymentInfo {
  id: string
  user_id: string
  project_id: string
  team_skill_id: string
  skill_name: string
  tool_type: string
  deploy_path: string
  install_path: string
  repo_version: number
  repo_hash: string
  installed_hash: string
  status: string
  tracking_enabled: boolean
  local_dirty: boolean
  last_seen_at: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ChangeItem {
  kind: 'field' | 'body' | 'resource'
  path: string
  label: string
  old?: unknown
  new?: unknown
  added_lines?: number
  removed_lines?: number
  diff?: string
  diff_truncated?: boolean
  change?: 'added' | 'removed' | 'modified'
}

export interface SkillVersionInfo {
  id: string
  skill_id: string
  seq: number
  label: string
  source: string
  created_by_name: string
  created_at: string | null
}

export interface PushDeploymentResponse {
  success: boolean
  no_change?: boolean
  status?: string
  conflict?: boolean
  change_items: ChangeItem[]
  diff_summary: string
  deployment?: UserSkillDeploymentInfo
  version?: SkillVersionInfo | null
  error?: string
}

export interface DeploymentLocalStatusResponse {
  success: boolean
  exists: boolean
  has_local_changes: boolean
  installed_hash: string
  current_hash: string
  status: string
  error?: string
}

export interface PullUpdateResponse {
  success: boolean
  conflict?: boolean
  deployment?: UserSkillDeploymentInfo
  error?: string
}

export interface ResumeTrackingResponse {
  success: boolean
  deployment?: UserSkillDeploymentInfo
  status?: string
  error?: string
}

export interface SkillDeploymentResponse {
  success: boolean
  deployment?: UserSkillDeploymentInfo
  deployed: { target: string; path: string }[]
  error?: string
}

export interface ProjectResponse {
  success: boolean
  project?: ProjectInfo
  error?: string
}

export interface ProjectListResponse {
  success: boolean
  projects: ProjectInfo[]
  error?: string
}

export interface ProjectDetailResponse {
  success: boolean
  project?: ProjectInfo
  skills: ProjectSkillInfo[]
  error?: string
}

export interface SyncStatusItem {
  skill_id: string
  version: number
  content_hash: string
  updated_at: string | null
}

export interface SyncStatusResponse {
  success: boolean
  skills: SyncStatusItem[]
  error?: string
}

export interface ChangeLogItem {
  id: string
  skill_id: string
  user_id: string
  user_display_name: string
  skill_display_name: string
  action: string
  version: number
  diff_summary: string
  change_items: ChangeItem[]
  created_at: string | null
}

export interface SyncChangesResponse {
  success: boolean
  changes: ChangeLogItem[]
  error?: string
}

export interface SyncPullItem {
  skill_id: string
  config: Record<string, unknown>
  vibeh_content: string
  version: number
  content_hash: string
}

export interface SyncPullResponse {
  success: boolean
  skills: SyncPullItem[]
  error?: string
}

// Project CRUD

export async function createProject(
  teamId: string,
  name: string,
  description: string = '',
): Promise<ProjectResponse> {
  const { data } = await apiClient.post<ProjectResponse>(
    `/teams/${teamId}/projects`,
    { name, description },
  )
  return data
}

export async function listProjects(
  teamId: string,
): Promise<ProjectListResponse> {
  // 开发者模式（跳过登录）下后端会因假 token 返回 401，这里回放假数据预览样式。
  if (DEV_SKIP_AUTH) return devMockProjectList(teamId)
  const { data } = await apiClient.get<ProjectListResponse>(
    `/teams/${teamId}/projects`,
  )
  return data
}

export async function getProject(
  projectId: string,
): Promise<ProjectDetailResponse> {
  // 开发者模式（跳过登录）下后端会因假 token 返回 401，这里回放假数据：
  // 让团队项目内有 Skill，且覆盖部署各状态以便预览所有操作按钮样式。
  if (DEV_SKIP_AUTH) return devMockProjectDetail(projectId)
  const { data } = await apiClient.get<ProjectDetailResponse>(
    `/projects/${projectId}`,
  )
  return data
}

export async function updateProject(
  projectId: string,
  payload: { name?: string; description?: string },
): Promise<ProjectResponse> {
  if (DEV_SKIP_AUTH) {
    return devMockUpdateProject(projectId, payload.name, payload.description)
  }
  const { data } = await apiClient.put<ProjectResponse>(
    `/projects/${projectId}`,
    payload,
  )
  return data
}

export async function deleteProject(
  projectId: string,
): Promise<{ success: boolean; error?: string }> {
  const { data } = await apiClient.delete(`/projects/${projectId}`)
  return data as { success: boolean; error?: string }
}

// Skill 关联

export async function addSkillToProject(
  projectId: string,
  skillId: string,
): Promise<{ success: boolean; error?: string }> {
  const { data } = await apiClient.post(
    `/projects/${projectId}/skills/${skillId}`,
  )
  return data as { success: boolean; error?: string }
}

export async function removeSkillFromProject(
  projectId: string,
  skillId: string,
): Promise<{ success: boolean; error?: string }> {
  const { data } = await apiClient.delete(
    `/projects/${projectId}/skills/${skillId}`,
  )
  return data as { success: boolean; error?: string }
}

export async function deployProjectSkill(
  projectId: string,
  skillId: string,
  payload: { tool_type: string; deploy_path: string; overwrite?: boolean },
): Promise<SkillDeploymentResponse> {
  // 灰度分流：编排开启 → 云端产物 → 本地代理落盘 → 云端登记（M0 §3.1）；
  // 否则走旧的一次性云端 deploy 端点（web 灰度回退，保现状可用）。
  if (isOrchestrationEnabled()) {
    return deployProjectSkillOrchestrated(projectId, skillId, payload)
  }
  const { data } = await apiClient.post<SkillDeploymentResponse>(
    `/projects/${projectId}/skills/${skillId}/deploy`,
    payload,
  )
  return data
}

export async function deployProjectSkillGlobal(
  projectId: string,
  skillId: string,
  payload: { tool_type: string; overwrite?: boolean },
): Promise<SkillDeploymentResponse> {
  // 全局部署：落本机平台目录 ~/.{tool}/skills，一次性安装、不跟踪、**始终覆盖同名旧副本**。
  // 编排（桌面）→ 本地代理 platform 落盘；web 灰度 → 后端 deploy 端点 scope=platform。
  if (isOrchestrationEnabled()) {
    return deployProjectSkillGlobalOrchestrated(projectId, skillId, payload)
  }
  const { data } = await apiClient.post<SkillDeploymentResponse>(
    `/projects/${projectId}/skills/${skillId}/deploy`,
    { tool_type: payload.tool_type, overwrite: true, scope: 'platform' },
  )
  return data
}

export async function stopTrackingDeployment(
  deploymentId: string,
  deleteFiles: boolean = false,
): Promise<{ success: boolean; error?: string }> {
  const { data } = await apiClient.delete<{ success: boolean; error?: string }>(
    `/skill-deployments/${deploymentId}`,
    { params: { delete_files: deleteFiles } },
  )
  return data
}

/**
 * 恢复跟踪：对已停止跟踪的部署就地重启跟踪（复用本地文件、重算基线/状态）。
 * @param deployment 编排模式必传：需 install_path 经本地代理实算 hash 上报。
 */
export async function resumeTrackingDeployment(
  deploymentId: string,
  deployment?: UserSkillDeploymentInfo | null,
): Promise<ResumeTrackingResponse> {
  if (isOrchestrationEnabled() && deployment) {
    return resumeTrackingOrchestrated(deploymentId, deployment)
  }
  const { data } = await apiClient.post<ResumeTrackingResponse>(
    `/skill-deployments/${deploymentId}/resume-tracking`,
  )
  return data
}

export async function promoteDeployment(
  deploymentId: string,
): Promise<SkillDeploymentResponse> {
  const { data } = await apiClient.post<SkillDeploymentResponse>(
    `/skill-deployments/${deploymentId}/promote`,
  )
  return data
}

/**
 * 推送本地改动到团队仓库。
 * @param deployment 编排模式必传：需读取 install_path/installed_hash 走 read-folder 上传（M0 §3.2）。
 * @param opts createVersion=true 时推送成功后创建一个版本快照（"是否更新版本序列号"）。
 */
export async function pushDeployment(
  deploymentId: string,
  deployment?: UserSkillDeploymentInfo | null,
  opts?: { createVersion?: boolean; versionLabel?: string },
): Promise<PushDeploymentResponse> {
  if (isOrchestrationEnabled() && deployment) {
    return pushOrchestrated(deploymentId, deployment, opts)
  }
  const { data } = await apiClient.post<PushDeploymentResponse>(
    `/skill-deployments/${deploymentId}/push`,
    null,
    { params: { create_version: opts?.createVersion ?? false, version_label: opts?.versionLabel ?? '' } },
  )
  return data
}

/**
 * 查询本地部署状态（dirty 检测）。
 * @param deployment 编排模式必传：经本地代理 hash 与基线比对（M0 §3.6）。
 */
export async function getDeploymentLocalStatus(
  deploymentId: string,
  deployment?: UserSkillDeploymentInfo | null,
): Promise<DeploymentLocalStatusResponse> {
  // 开发者模式：直接按假部署对象回放本地状态，避免假 token 触发 401 与 8s 轮询报错刷屏。
  if (DEV_SKIP_AUTH) {
    return {
      success: true,
      exists: !!deployment && deployment.status !== 'missing',
      has_local_changes: deployment?.local_dirty ?? false,
      installed_hash: deployment?.installed_hash ?? '',
      current_hash: deployment?.repo_hash ?? '',
      status: deployment?.status ?? 'synced',
    }
  }
  if (isOrchestrationEnabled() && deployment) {
    return getLocalStatusOrchestrated(deploymentId, deployment)
  }
  const { data } = await apiClient.get<DeploymentLocalStatusResponse>(
    `/skill-deployments/${deploymentId}/local-status`,
  )
  return data
}

/**
 * 拉取团队最新覆盖本地。
 * @param deployment 编排模式必传：云端取产物 → 本地代理覆盖写 → 云端 commit-pull（M0 §3.3）。
 */
export async function pullUpdateDeployment(
  deploymentId: string,
  overwrite: boolean = false,
  deployment?: UserSkillDeploymentInfo | null,
): Promise<PullUpdateResponse> {
  if (isOrchestrationEnabled() && deployment) {
    return pullUpdateOrchestrated(deploymentId, deployment, overwrite)
  }
  const { data } = await apiClient.post<PullUpdateResponse>(
    `/skill-deployments/${deploymentId}/pull-update`,
    { overwrite },
  )
  return data
}

/**
 * AI 合并预览（冲突一键合并第一步）。
 * @param deployment 必传：编排模式经本地代理读取本地内容上传云端三方合并。
 */
export async function mergePreviewDeployment(
  deploymentId: string,
  deployment?: UserSkillDeploymentInfo | null,
): Promise<MergePreviewResponse> {
  if (isOrchestrationEnabled() && deployment) {
    return mergePreviewOrchestrated(deploymentId, deployment)
  }
  return {
    success: false,
    error: 'AI 合并仅桌面客户端支持',
    preview_change_items: [],
    manual_conflicts: [],
    notes: [],
    merge_available: false,
    theirs_hash: '',
  }
}

/**
 * AI 合并提交（冲突一键合并第二步）：写回团队仓库 + 覆盖本地 + 登记同步。
 */
export async function mergeCommitDeployment(
  deploymentId: string,
  merged: MergedContent,
  expectedTheirsHash: string,
  deployment?: UserSkillDeploymentInfo | null,
  mineFiles?: MergePreviewResponse['mineFiles'],
): Promise<MergeCommitResult> {
  if (isOrchestrationEnabled() && deployment) {
    return mergeCommitOrchestrated(deploymentId, deployment, merged, expectedTheirsHash, mineFiles)
  }
  return { success: false, error: 'AI 合并仅桌面客户端支持' }
}

// 同步

export async function getSyncStatus(
  projectId: string,
): Promise<SyncStatusResponse> {
  const { data } = await apiClient.get<SyncStatusResponse>(
    `/projects/${projectId}/sync/status`,
  )
  return data
}

export async function getSyncChanges(
  projectId: string,
  sinceVersion: number = 0,
): Promise<SyncChangesResponse> {
  // 开发者模式：无后端，返回空动态（成功），避免轮询 401 报错刷屏。
  if (DEV_SKIP_AUTH) return { success: true, changes: [] }
  const { data } = await apiClient.get<SyncChangesResponse>(
    `/projects/${projectId}/sync/changes`,
    { params: { since_version: sinceVersion } },
  )
  return data
}

export async function syncPull(
  projectId: string,
  skillIds: string[],
): Promise<SyncPullResponse> {
  const { data } = await apiClient.post<SyncPullResponse>(
    `/projects/${projectId}/sync/pull`,
    { skill_ids: skillIds },
  )
  return data
}
