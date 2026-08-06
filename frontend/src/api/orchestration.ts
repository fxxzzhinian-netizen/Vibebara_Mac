/**
 * 前端编排链路（M4 前端分流，编排者=前端，见 M0 §3 / §9）。
 *
 * 桌面客户端形态下「云端够不着本地代理」，原一次性的 deploy/push/pull/import 必须由
 * 前端串成多步：「云端构建产物 → 本地代理落盘/读盘 → 云端登记/解析」。本模块封装这些
 * 编排函数，返回值刻意与旧的一次性 API（projects.ts / skillStore.ts）**同形状**，
 * 以便上层 store/view 在灰度分流时**无需改调用签名**。
 *
 * 云端协作端点 DTO 严格对齐 `contracts/local-agent-api.md` §9。
 *
 * 云端依赖（M1 已落地）：build-artifact / register-deployment / commit-pull /
 * push（内容版）/ import-content / merge-preview / merge-apply / commit-merge 等
 * 协作端点已在后端 `backend/app/api/projects.py` 实现。这些编排路径在
 * runtimeConfig.orchestration=true（桌面/联调）时启用；web 灰度默认走旧端点
 * （见各 api/*.ts 的分流）。
 */
import { cloudClient } from './client'
import { TOOL_TYPES } from '@/constants/platforms'
import * as localAgent from './localAgent'
import type {
  ResourcePayload,
  ToolType,
  FilePayload,
  UnifiedSkillPackage,
} from './localAgent'
import type {
  SkillDeploymentResponse,
  PullUpdateResponse,
  PushDeploymentResponse,
  DeploymentLocalStatusResponse,
  ResumeTrackingResponse,
  UserSkillDeploymentInfo,
  ChangeItem,
} from './projects'
import type {
  DeployResponse,
  MutationResponse,
} from './skillStore'
import type { InstalledAtStatus } from './skillForge'

// ===================== 云端协作端点 DTO（契约 §9）=====================

/** 资源清单项：云端把 Store 的 scripts/references/assets 随产物下发，再转交 write-skill。 */
export interface CloudResourceItem {
  path: string
  transfer: localAgent.ResourceTransfer
  encoding?: localAgent.ContentEncoding
  content?: string
  url?: string
  sha256?: string
  size?: number
}

/** 抽象快照（云端权威生成；deploy/pull 由云端从构建产物直接产出）。 */
export type AbstractSnapshot = Record<string, unknown>

/**
 * ① 云端构建产物（不写盘、不登记）。
 * R-A 统一口径：响应体为 snake_case（与后端 BuildArtifactResponse 对齐）。
 */
export interface BuildArtifactResponse {
  success: boolean
  skill_id: string
  tool: ToolType
  contents: Record<string, string>
  resources: CloudResourceItem[]
  repo_hash: string
  repo_version: number
  abstract_snapshot: AbstractSnapshot
  error?: string
}

/** ④ 云端登记部署元数据（对应原 deploy_project_skill 的写库段）。 */
export interface RegisterDeploymentRequest {
  tool: ToolType
  deployPath: string
  installPath: string
  installedHash: string
  repoHash: string
  repoVersion: number
  abstractSnapshot: AbstractSnapshot
  overwrite?: boolean
}

/** 拉取提交（对应原 pull-update 的写库段）。 */
export interface CommitPullRequest {
  installedHash: string
  repoHash: string
  repoVersion: number
  abstractSnapshot: AbstractSnapshot
}

/** 推送（接收本地 install 内容上传，云端 diff + 写回 Store）。 */
export interface PushDeploymentRequest {
  currentHash: string
  files: FilePayload[]
  createVersion?: boolean
  versionNumber?: string
  versionLabel?: string
}

/** 导入（接收本地文件夹内容上传，云端落 Store）。 */
export interface ImportContentRequest {
  files: FilePayload[]
  origin?: string
  scope?: 'personal' | 'team'
  teamId?: string
}

// ===================== 云端编排端点调用（M1 已落地，见 backend/app/api/projects.py）=====================

/** POST /projects/{pid}/skills/{sid}/build-artifact —— 项目 Skill 构建产物。 */
async function buildArtifactForProjectSkill(
  projectId: string,
  skillId: string,
  tool: ToolType,
): Promise<BuildArtifactResponse> {
  // 云端协作端点（已实现）：返回 contents+resources+repoHash+abstractSnapshot。
  const { data } = await cloudClient.post<BuildArtifactResponse>(
    `/projects/${projectId}/skills/${skillId}/build-artifact`,
    { tool },
  )
  return data
}

/** POST /skill-deployments/{id}/build-artifact —— 拉取时取团队最新产物。 */
async function buildArtifactForDeployment(
  deploymentId: string,
): Promise<BuildArtifactResponse> {
  // 云端协作端点（已实现）：build 团队仓库最新 → contents+resources+teamHash。
  const { data } = await cloudClient.post<BuildArtifactResponse>(
    `/skill-deployments/${deploymentId}/build-artifact`,
    {},
  )
  return data
}

/** POST /skill-forge/store/{sid}/build-artifact —— 个人/团队仓库 Skill 构建产物。 */
async function buildArtifactForStoreSkill(
  skillId: string,
  tool: ToolType,
): Promise<BuildArtifactResponse> {
  // 云端协作端点（已实现）：契约 §9 列了 project/deployment build-artifact；
  // 此为 store 级 build-artifact（返回 contents+resources），用于个人仓库部署。
  const { data } = await cloudClient.post<BuildArtifactResponse>(
    `/skill-forge/store/${skillId}/build-artifact`,
    { tool },
  )
  return data
}

/** POST /projects/{pid}/skills/{sid}/register-deployment —— 登记部署元数据。 */
async function registerDeployment(
  projectId: string,
  skillId: string,
  body: RegisterDeploymentRequest,
): Promise<SkillDeploymentResponse> {
  // 云端协作端点（已实现）：UPSERT UserSkillDeployment + 写 change log。
  const { data } = await cloudClient.post<SkillDeploymentResponse>(
    `/projects/${projectId}/skills/${skillId}/register-deployment`,
    body,
  )
  return data
}

/** POST /skill-deployments/{id}/commit-pull —— 拉取提交登记。 */
async function commitPull(
  deploymentId: string,
  body: CommitPullRequest,
): Promise<PullUpdateResponse> {
  // 云端协作端点（已实现）：status=synced, local_dirty=false, 写 change log(pulled)。
  const { data } = await cloudClient.post<PullUpdateResponse>(
    `/skill-deployments/${deploymentId}/commit-pull`,
    body,
  )
  return data
}

/** POST /skill-deployments/{id}/push —— 内容版推送（入参从路径改为 currentHash+files）。 */
async function pushContent(
  deploymentId: string,
  body: PushDeploymentRequest,
): Promise<PushDeploymentResponse> {
  // 云端协作端点（已实现）：接收 {currentHash, files}（临时目录重建 → diff → 写回 Store）。
  const { data } = await cloudClient.post<PushDeploymentResponse>(
    `/skill-deployments/${deploymentId}/push`,
    body,
  )
  return data
}

/** POST /skill-forge/store/import-content —— 内容版导入。 */
async function importContent(
  body: ImportContentRequest,
): Promise<MutationResponse> {
  // 云端协作端点（已实现）：临时目录重建 files → 复用 import_from_external 解析落 Store。
  const { data } = await cloudClient.post<MutationResponse>(
    '/skill-forge/store/import-content',
    body,
  )
  return data
}

// ===================== 内部辅助 =====================

/** CloudResourceItem[] → write-skill ResourcePayload[]（结构同形，直接透传）。 */
function toWriteResources(items: CloudResourceItem[] | undefined): ResourcePayload[] {
  if (!items) return []
  return items.map((r) => ({
    path: r.path,
    transfer: r.transfer,
    encoding: r.encoding,
    content: r.content,
    url: r.url,
    sha256: r.sha256,
    size: r.size,
  }))
}

function asTool(t: string): ToolType {
  if (t === 'codex') return 'codex'
  if (t === 'windsurf') return 'windsurf'
  if (t === 'claude') return 'claude'
  if (t === 'kiro') return 'kiro'
  if (t === 'trae') return 'trae'
  if (t === 'qoder') return 'qoder'
  if (t === 'workbuddy') return 'workbuddy'
  return 'cursor'
}

// ===================== 编排：项目 Skill 部署（M0 §3.1）=====================

/**
 * 部署项目 Skill（四步：云端产物 → 本地落盘 → 本地 hash → 云端登记）。
 * 返回 SkillDeploymentResponse（与旧 deployProjectSkill 同形）。
 */
export async function deployProjectSkillOrchestrated(
  projectId: string,
  skillId: string,
  payload: { tool_type: string; deploy_path: string; overwrite?: boolean },
): Promise<SkillDeploymentResponse> {
  const tool = asTool(payload.tool_type)
  try {
    // ① 云端构建产物（不写盘、不登记）
    const artifact = await buildArtifactForProjectSkill(projectId, skillId, tool)
    if (!artifact.success) {
      return { success: false, deployed: [], error: artifact.error || '云端构建失败' }
    }

    // ② 本地代理落盘（覆盖语义） + ③ write-skill 顺带返回 installedHash（省一次 /local/hash）
    // 【M5-b 任务③】deploy_path = 用户确认选定的目标根，作为本地代理写盘授权来源
    // （write-skill 据此登记可写根 + 逃逸校验；browse 不再被动授权）。
    const write = await localAgent.writeSkill({
      deployPath: payload.deploy_path,
      scope: 'project',
      tool,
      skillId: artifact.skill_id || skillId,
      contents: artifact.contents,
      resources: toWriteResources(artifact.resources),
      overwrite: payload.overwrite ?? false,
      ensureGitignore: true,
    })

    // ④ 云端登记部署元数据 + change log
    return await registerDeployment(projectId, skillId, {
      tool,
      deployPath: payload.deploy_path,
      installPath: write.installPath,
      installedHash: write.installedHash,
      repoHash: artifact.repo_hash,
      repoVersion: artifact.repo_version,
      abstractSnapshot: artifact.abstract_snapshot,
      overwrite: payload.overwrite,
    })
  } catch (e) {
    return { success: false, deployed: [], error: errMsg(e) }
  }
}

/**
 * 全局部署项目 Skill（落本机平台目录 ~/.{tool}/skills/{skillId}，不登记跟踪）。
 * 复用项目 build-artifact 取产物（兼容团队/项目权限），交本地代理以 platform scope 落盘。
 * 与项目级部署的差异：scope=platform、无 deployPath、不调用 register-deployment。
 *
 * 全局部署语义：**始终覆盖同名旧副本**（一次性安装、不跟踪更新）。因此忽略 payload.overwrite，
 * 强制 overwrite=true，避免「同名已存在」时本地代理抛 INSTALL_EXISTS 导致二次全局部署失败。
 */
export async function deployProjectSkillGlobalOrchestrated(
  projectId: string,
  skillId: string,
  payload: { tool_type: string; overwrite?: boolean },
): Promise<SkillDeploymentResponse> {
  const tool = asTool(payload.tool_type)
  try {
    const artifact = await buildArtifactForProjectSkill(projectId, skillId, tool)
    if (!artifact.success) {
      return { success: false, deployed: [], error: artifact.error || '云端构建失败' }
    }
    const write = await localAgent.writeSkill({
      scope: 'platform',
      tool,
      skillId: artifact.skill_id || skillId,
      contents: artifact.contents,
      resources: toWriteResources(artifact.resources),
      overwrite: true,
      ensureGitignore: false,
    })
    return { success: true, deployed: [{ target: tool, path: write.installPath }] }
  } catch (e) {
    return { success: false, deployed: [], error: errMsg(e) }
  }
}

// ===================== 编排：拉取更新（M0 §3.3）=====================

export async function pullUpdateOrchestrated(
  deploymentId: string,
  deployment: UserSkillDeploymentInfo,
  overwrite: boolean,
): Promise<PullUpdateResponse> {
  const tool = asTool(deployment.tool_type)
  try {
    // 本地当前 hash 与基线比对：有未推送改动且未授权覆盖 → 拦截冲突
    const cur = await localAgent.hashOne(deployment.install_path)
    if (cur.exists && cur.hash !== deployment.installed_hash && !overwrite) {
      return { success: false, conflict: true }
    }

    // 取团队最新产物（云端）
    const artifact = await buildArtifactForDeployment(deploymentId)
    if (!artifact.success) {
      return { success: false, error: artifact.error || '云端构建失败' }
    }

    // 覆盖写本地（write-skill overwrite:true 顺带回 installedHash）
    const write = await localAgent.writeSkill({
      deployPath: deployment.deploy_path,
      scope: 'project',
      tool,
      skillId: artifact.skill_id,
      contents: artifact.contents,
      resources: toWriteResources(artifact.resources),
      overwrite: true,
      ensureGitignore: true,
    })

    // 云端登记拉取提交
    return await commitPull(deploymentId, {
      installedHash: write.installedHash,
      repoHash: artifact.repo_hash,
      repoVersion: artifact.repo_version,
      abstractSnapshot: artifact.abstract_snapshot,
    })
  } catch (e) {
    return { success: false, error: errMsg(e) }
  }
}

// ===================== 编排：推送（M0 §3.2）=====================

export async function pushOrchestrated(
  deploymentId: string,
  deployment: UserSkillDeploymentInfo,
  opts?: { createVersion?: boolean; versionNumber?: string; versionLabel?: string },
): Promise<PushDeploymentResponse> {
  try {
    const cur = await localAgent.hashOne(deployment.install_path)
    if (!cur.exists) {
      return {
        success: false,
        change_items: [],
        diff_summary: '',
        status: 'missing',
        error: '本地部署目录缺失，无法推送',
      }
    }
    if (cur.hash === deployment.installed_hash) {
      // 本地无改动，直接返回（与旧 push_deployment no_change 语义一致）
      return { success: true, no_change: true, change_items: [], diff_summary: '' }
    }

    // 读取本地 install 全部文件（文本/二进制按契约编码）
    const folder = await localAgent.readFolder({
      path: deployment.install_path,
      include: 'all',
    })

    // 上传云端解析 + diff + 写回 Store
    return await pushContent(deploymentId, {
      currentHash: cur.hash,
      files: folder.files,
      createVersion: opts?.createVersion ?? false,
      versionNumber: opts?.versionNumber ?? '',
      versionLabel: opts?.versionLabel ?? '',
    })
  } catch (e) {
    return {
      success: false,
      change_items: [],
      diff_summary: '',
      error: errMsg(e),
    }
  }
}

// ===================== 编排：AI 辅助合并（冲突一键合并，docs/design/ai-assisted-merge.md）=====================

/** 资源处置：apply 以 mine 树为基底应用。 */
export interface MergeResourceOp {
  path: string
  action: 'use_mine' | 'use_theirs' | 'write_text' | 'delete'
  encoding?: string
  content?: string
}

/** 合并稿：preview 产出、apply 回送（预览框编辑后回送）。 */
export interface MergedContent {
  body: string
  config: Record<string, unknown>
  resource_ops: MergeResourceOp[]
}

export interface MergeManualConflict {
  path: string
  reason: string
}

/** merge-preview 响应。 */
export interface MergePreviewResponse {
  success: boolean
  error?: string
  merged?: MergedContent
  preview_change_items: ChangeItem[]
  manual_conflicts: MergeManualConflict[]
  notes: string[]
  merge_available: boolean
  theirs_hash: string
  /**
   * 客户端编排回填（server 不返回）：preview 阶段读到的本地 mine 文件树。
   * 供 commit 复用，使 preview/apply 只读一次本地（R-D），并保证「合并稿所基于的
   * mine」与 apply 落库的 mine 完全一致。
   */
  mineFiles?: FilePayload[]
}

/** merge-apply 响应（artifact 为 native 构建产物，供覆盖落盘）。 */
interface MergeApplyResponse {
  success: boolean
  conflict?: boolean
  error?: string
  artifact?: BuildArtifactResponse
}

/** commit-merge / 合并提交整链路结果。 */
export interface MergeCommitResult {
  success: boolean
  conflict?: boolean
  deployment?: UserSkillDeploymentInfo
  error?: string
}

function emptyPreview(error: string): MergePreviewResponse {
  return {
    success: false,
    error,
    preview_change_items: [],
    manual_conflicts: [],
    notes: [],
    merge_available: false,
    theirs_hash: '',
  }
}

/**
 * AI 合并预览：本地代理读取 install 内容上传 → 云端取 base/theirs 三方合并 → 返回可编辑合并稿。
 * 只算不写，不改本地、不改团队仓库。
 */
export async function mergePreviewOrchestrated(
  deploymentId: string,
  deployment: UserSkillDeploymentInfo,
): Promise<MergePreviewResponse> {
  try {
    const cur = await localAgent.hashOne(deployment.install_path)
    if (!cur.exists) {
      return emptyPreview('本地部署目录缺失，无法合并')
    }
    const folder = await localAgent.readFolder({
      path: deployment.install_path,
      include: 'all',
    })
    const { data } = await cloudClient.post<MergePreviewResponse>(
      `/skill-deployments/${deploymentId}/merge-preview`,
      { currentHash: cur.hash, files: folder.files },
    )
    // R-D：回填本地 mine 文件树，供 commit 复用，避免 apply 二次 read-folder。
    return { ...data, mineFiles: folder.files }
  } catch (e) {
    return emptyPreview(errMsg(e))
  }
}

/**
 * AI 合并提交：再次上传本地内容 + 合并稿 → 云端乐观锁校验并写回团队仓库 → 取产物
 * 覆盖落盘 → 云端 commit-merge 登记。任一步失败回传 error/conflict。
 */
export async function mergeCommitOrchestrated(
  deploymentId: string,
  deployment: UserSkillDeploymentInfo,
  merged: MergedContent,
  expectedTheirsHash: string,
  mineFiles?: FilePayload[],
): Promise<MergeCommitResult> {
  const tool = asTool(deployment.tool_type)
  try {
    // R-D：优先复用 preview 阶段读到的本地 mine 文件，保证「合并稿所基于的 mine」与
    // apply 落库的 mine 一致，且 preview/apply 只读一次本地；缺失时（如绕过 preview
    // 直接提交）回退再读一次盘。
    const files =
      mineFiles && mineFiles.length > 0
        ? mineFiles
        : (
            await localAgent.readFolder({
              path: deployment.install_path,
              include: 'all',
            })
          ).files
    const { data: apply } = await cloudClient.post<MergeApplyResponse>(
      `/skill-deployments/${deploymentId}/merge-apply`,
      { files, merged, expectedTheirsHash },
    )
    if (!apply.success || !apply.artifact) {
      return { success: false, conflict: apply.conflict, error: apply.error || '合并提交失败' }
    }
    const artifact = apply.artifact
    const write = await localAgent.writeSkill({
      deployPath: deployment.deploy_path,
      scope: 'project',
      tool,
      skillId: artifact.skill_id || deployment.team_skill_id,
      contents: artifact.contents,
      resources: toWriteResources(artifact.resources),
      overwrite: true,
      ensureGitignore: true,
    })
    const { data } = await cloudClient.post<MergeCommitResult>(
      `/skill-deployments/${deploymentId}/commit-merge`,
      {
        installedHash: write.installedHash,
        repoHash: artifact.repo_hash,
        repoVersion: artifact.repo_version,
        abstractSnapshot: artifact.abstract_snapshot,
      },
    )
    return data
  } catch (e) {
    return { success: false, error: errMsg(e) }
  }
}

// ===================== 编排：恢复跟踪（复用本地文件就地恢复）=====================

/**
 * 恢复跟踪：本地代理实算 install 目录 hash 上报 → 云端重启跟踪、重算基线/状态。
 * 本地目录缺失（exists=false）→ 直接返回 missing，由调用方引导「重新部署」，不打云端。
 */
export async function resumeTrackingOrchestrated(
  deploymentId: string,
  deployment: UserSkillDeploymentInfo,
): Promise<ResumeTrackingResponse> {
  try {
    const cur = await localAgent.hashOne(deployment.install_path)
    if (!cur.exists) {
      return { success: false, status: 'missing', error: '本地部署目录缺失，请重新部署' }
    }
    const { data } = await cloudClient.post<ResumeTrackingResponse>(
      `/skill-deployments/${deploymentId}/resume-tracking`,
      { installedHash: cur.hash },
    )
    return data
  } catch (e) {
    return { success: false, error: errMsg(e) }
  }
}

// ===================== 编排：本地状态（M0 §3.6 方式二）=====================

/**
 * 本地状态：本地代理算 hash → 与基线 installed_hash 比对判定 dirty。
 * dirty 判定纯本地 hash 比较（M0 §3.6），无需云端往返。
 */
export async function getLocalStatusOrchestrated(
  _deploymentId: string,
  deployment: UserSkillDeploymentInfo,
): Promise<DeploymentLocalStatusResponse> {
  try {
    const cur = await localAgent.hashOne(deployment.install_path)
    const dirty = cur.exists && cur.hash !== deployment.installed_hash
    const status = !cur.exists ? 'missing' : dirty ? 'changed' : 'synced'
    return {
      success: true,
      exists: cur.exists,
      has_local_changes: dirty,
      installed_hash: deployment.installed_hash,
      current_hash: cur.hash,
      status,
    }
  } catch (e) {
    return {
      success: false,
      exists: false,
      has_local_changes: false,
      installed_hash: deployment.installed_hash,
      current_hash: '',
      status: 'error',
      error: errMsg(e),
    }
  }
}

// ===================== 编排：个人/团队仓库 Skill 部署（M0 §3.1 变体）=====================

/**
 * 个人/团队仓库 Skill 部署到平台或项目目录。
 * destPath 有值 → scope=project；无值 → scope=platform（落本地平台 skill 目录）。
 * 注意：个人仓库部署不登记 deployment（与旧 deployNativeSkill 一致）。
 */
export async function deployNativeSkillOrchestrated(
  id: string,
  target: string,
  destPath?: string,
): Promise<DeployResponse> {
  const tool = asTool(target)
  const scope = destPath ? 'project' : 'platform'
  try {
    const artifact = await buildArtifactForStoreSkill(id, tool)
    if (!artifact.success) {
      return { success: false, deployed: [], error: artifact.error || '云端构建失败' }
    }
    const write = await localAgent.writeSkill({
      deployPath: destPath,
      scope,
      tool,
      skillId: artifact.skill_id || id,
      contents: artifact.contents,
      resources: toWriteResources(artifact.resources),
      overwrite: true,
      ensureGitignore: scope === 'project',
    })
    // 平台部署状态（deployed_cursor/codex）：薄代理形态下「本机是否已装」由本地代理
    // scan.installedAt 实时回答、前端用其展示（见 getPlatformInstalledStatus + 决定①），
    // 云端 cloud 模式不依赖该标记，故此处无需回写云端。
    return { success: true, deployed: [{ target, path: write.installPath }] }
  } catch (e) {
    return { success: false, deployed: [], error: errMsg(e) }
  }
}

// ===================== 平台安装状态（决定①：deployed_* 降级为 scan.installedAt）=====================

/**
 * 经本地代理实时探测「某 Skill 是否已装到本机 cursor/codex/windsurf」（决定①）。
 *
 * 薄代理形态下 `SkillPackage.deployed_cursor/codex/windsurf` 由后端探测后端机器 home 得来，
 * cloud 下无意义；改由本地代理扫描**用户机器**的平台 skill 目录（health.platformSkillDirs），
 * 按 `scan.installedAt` 汇总每个 skillId 的安装状态。前端展示点据此覆盖 deployed_* 展示。
 *
 * 返回 `{ [安装目录自然名]: { cursor, codex, windsurf, ... } }`；本地代理不可达/目录为空时返回空表（调用方回退）。
 */
export async function getPlatformInstalledStatus(): Promise<
  Record<string, InstalledAtStatus>
> {
  const map: Record<string, InstalledAtStatus> = {}
  let dirs: { cursor: string; codex: string; windsurf: string; claude: string; kiro: string; trae: string; qoder: string; workbuddy: string }
  try {
    const h = await localAgent.health()
    dirs = h.platformSkillDirs
  } catch {
    return map
  }
  // 扫描八个平台目录；每个包的 installedAt 已对各平台目录各自探测，直接汇总即可。
  for (const dir of [dirs.cursor, dirs.codex, dirs.windsurf, dirs.claude, dirs.kiro, dirs.trae, dirs.qoder, dirs.workbuddy]) {
    if (!dir) continue
    try {
      const res = await localAgent.scan({ rootDir: dir })
      for (const p of res.packages) {
        map[p.id] = {
          cursor: p.installedAt.cursor,
          codex: p.installedAt.codex,
          windsurf: p.installedAt.windsurf,
          claude: p.installedAt.claude,
          kiro: p.installedAt.kiro,
          trae: p.installedAt.trae,
          qoder: p.installedAt.qoder,
          workbuddy: p.installedAt.workbuddy,
        }
      }
    } catch {
      // 平台目录可能不存在/为空 → 忽略，对应 skill 视为未安装
    }
  }
  return map
}

// ===================== 编排：检索各 IDE 全局目录 Skill（从 IDE 导入）=====================

/** 一个 IDE 全局 skill 目录的检索结果分组。 */
export interface IdeSkillGroup {
  tool: ToolType
  dir: string
  packages: UnifiedSkillPackage[]
}

/**
 * 检索本机各受支持 IDE 的全局 skill 目录（health.platformSkillDirs），逐目录 scan，
 * 按 IDE 分组返回（仅保留含 skill 的目录）。
 *
 * 与 getPlatformInstalledStatus 同模式，但这里按 IDE 分组保留完整包列表用于导入选择；
 * origin 以「扫描的是哪个 IDE 目录」为准（比 scan 自带的简化 origin 更准确），
 * 导入时用 group.tool 作为 origin。
 */
export async function scanPlatformGlobalSkillsOrchestrated(): Promise<IdeSkillGroup[]> {
  const h = await localAgent.health()
  const dirs = h.platformSkillDirs
  const order: ToolType[] = [...TOOL_TYPES]
  const groups: IdeSkillGroup[] = []
  for (const tool of order) {
    const dir = dirs[tool]
    if (!dir) continue
    try {
      const res = await localAgent.scan({ rootDir: dir })
      if (res.packages.length) groups.push({ tool, dir, packages: res.packages })
    } catch {
      // 目录不存在/为空 → 跳过
    }
  }
  return groups
}

// ===================== 编排：从本地文件夹导入（M0 §3.5）=====================

export async function importContentOrchestrated(
  sourcePath: string,
  origin?: string,
  scope: 'personal' | 'team' = 'personal',
  teamId?: string,
): Promise<MutationResponse> {
  try {
    const folder = await localAgent.readFolder({ path: sourcePath, include: 'skill' })
    return await importContent({
      files: folder.files,
      origin,
      scope,
      teamId,
    })
  } catch (e) {
    return { success: false, error: errMsg(e) }
  }
}

// ===================== 错误信息提取 =====================

function errMsg(e: unknown): string {
  if (e instanceof localAgent.LocalAgentCallError) {
    return `[本地代理:${e.code}] ${e.message}`
  }
  const anyE = e as { response?: { data?: { detail?: string; error?: string } }; message?: string }
  return (
    anyE?.response?.data?.detail ||
    anyE?.response?.data?.error ||
    anyE?.message ||
    '编排请求失败'
  )
}
