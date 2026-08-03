import logging
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel

from app.api.auth import get_current_user_id
from app.schemas.project import (
    BuildArtifactRequest,
    BuildArtifactResponse,
    CommitMergeRequest,
    CommitPullRequest,
    DeploymentLocalStatusResponse,
    MergeApplyRequest,
    MergeApplyResponse,
    MergePreviewResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdateRequest,
    PullUpdateRequest,
    PullUpdateResponse,
    PushContentRequest,
    PushDeploymentResponse,
    RegisterDeploymentRequest,
    ResumeTrackingRequest,
    SkillDeployRequest,
    SkillDeploymentResponse,
    SyncChangesResponse,
    SyncPullRequest,
    SyncPullResponse,
    SyncPullItem,
    SyncStatusResponse,
    UserSkillDeploymentListResponse,
)
from app.services import project_service, team_service
from app.services.native_skill_store import NativeSkillStore
from app.services.skill_forge_service import scan_external_packages

logger = logging.getLogger(__name__)

api_router = APIRouter(tags=["projects"])


async def _check_project_access(project_id: str, user_id: str):
    """校验用户是否有权访问该项目（通过 team 成员关系）"""
    team_id = await project_service.get_project_team_id(project_id)
    if not team_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权访问该项目")
    return team_id


# ------------------------------------------------------------------
# Project CRUD
# ------------------------------------------------------------------

@api_router.post("/teams/{team_id}/projects", response_model=ProjectResponse)
async def create_project(
    team_id: str,
    data: ProjectCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权在该团队创建项目")
    try:
        project = await project_service.create_project(
            team_id, data.name, data.description, user_id
        )
        return {"success": True, "project": project}
    except Exception as e:
        logger.exception("[projects] 创建失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/teams/{team_id}/projects", response_model=ProjectListResponse)
async def list_projects(
    team_id: str, user_id: str = Depends(get_current_user_id)
):
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权访问该团队")
    projects = await project_service.list_projects(team_id, user_id)
    return {"success": True, "projects": projects}


@api_router.get("/projects/{project_id}", response_model=ProjectDetailResponse)
async def get_project(
    project_id: str, user_id: str = Depends(get_current_user_id)
):
    await _check_project_access(project_id, user_id)
    project = await project_service.get_project(project_id)
    skills = await project_service.list_project_skills(project_id, user_id)
    return {"success": True, "project": project, "skills": skills}


@api_router.put("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    data: ProjectUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    await _check_project_access(project_id, user_id)
    project = await project_service.update_project(
        project_id, data.name, data.description, user_id
    )
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True, "project": project}


@api_router.delete("/projects/{project_id}")
async def delete_project(
    project_id: str, user_id: str = Depends(get_current_user_id)
):
    team_id = await _check_project_access(project_id, user_id)
    role = await team_service.get_member_role(team_id, user_id)
    if role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可删除项目")
    success = await project_service.delete_project(project_id, user_id)
    if not success:
        raise HTTPException(status_code=404, detail="项目不存在")
    return {"success": True}


# ------------------------------------------------------------------
# Skill 关联
# ------------------------------------------------------------------

@api_router.post("/projects/{project_id}/skills/{skill_id}")
async def add_skill(
    project_id: str,
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await _check_project_access(project_id, user_id)
    return await project_service.add_skill_to_project(project_id, skill_id, user_id)


@api_router.get("/projects/{project_id}/skills")
async def list_project_skills(
    project_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await _check_project_access(project_id, user_id)
    skills = await project_service.list_project_skills(project_id, user_id)
    return {"success": True, "skills": skills}


@api_router.delete("/projects/{project_id}/skills/{skill_id}")
async def remove_skill(
    project_id: str,
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    await _check_project_access(project_id, user_id)
    return await project_service.remove_skill_from_project(project_id, skill_id, user_id)


@api_router.post("/teams/{team_id}/skills/from-personal/{skill_id}")
async def copy_personal_skill_to_team(
    team_id: str,
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """将当前用户的个人 Skill 复制一份放入团队 Skill 仓库。"""
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权操作该团队")
    try:
        skill = await NativeSkillStore.copy_to_team(skill_id, team_id, user_id)
        return {"success": True, "skill": skill}
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except PermissionError as e:
        return {"success": False, "error": str(e)}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[teams/skills] 放入团队失败: {skill_id}")
        raise HTTPException(status_code=500, detail=str(e))


class TeamLocalScanRequest(BaseModel):
    path: str


@api_router.post("/teams/{team_id}/skills/scan-local")
async def scan_local_skills_for_team(
    team_id: str,
    data: TeamLocalScanRequest,
    user_id: str = Depends(get_current_user_id),
):
    """解析本地文件夹，返回其中可导入的 Skill 列表（不落盘、不改全局扫描状态）。"""
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权操作该团队")
    try:
        packages = await scan_external_packages(data.path)
        return {"success": True, "packages": packages}
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "packages": [], "error": str(e)}
    except Exception as e:
        logger.exception("[teams/skills] 解析本地文件夹失败")
        return {"success": False, "packages": [], "error": str(e)}


class TeamLocalImportRequest(BaseModel):
    source_path: str
    origin: Optional[str] = None


@api_router.post("/teams/{team_id}/skills/import-local")
async def import_local_skill_to_team(
    team_id: str,
    data: TeamLocalImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """从本地文件夹直接导入一个 Skill 到团队 Skill 仓库。"""
    if not await team_service.is_team_member(team_id, user_id):
        raise HTTPException(status_code=403, detail="无权操作该团队")
    try:
        skill = await NativeSkillStore.import_external_to_team(
            data.source_path, team_id, user_id, origin=data.origin
        )
        return {"success": True, "skill": skill}
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except (PermissionError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("[teams/skills] 本地文件夹导入团队失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post(
    "/projects/{project_id}/skills/{skill_id}/deploy",
    response_model=SkillDeploymentResponse,
)
async def deploy_project_skill(
    project_id: str,
    skill_id: str,
    data: SkillDeployRequest,
    user_id: str = Depends(get_current_user_id),
):
    """[一次性端点 · 灰度保留] 后端直接构建+写后端盘+登记，供 local 形态使用。"""
    await _check_project_access(project_id, user_id)
    return await project_service.deploy_project_skill(
        project_id=project_id,
        skill_id=skill_id,
        user_id=user_id,
        tool_type=data.tool_type,
        deploy_path=data.deploy_path,
        overwrite=data.overwrite,
        scope=data.scope,
    )


# ------------------------------------------------------------------
# 方案 B · M4 云端编排端点（薄代理；前端串联本地代理落盘/算 hash）
# 对应 contracts/local-agent-api.md §9 镜像 DTO。
# ------------------------------------------------------------------

@api_router.post(
    "/projects/{project_id}/skills/{skill_id}/build-artifact",
    response_model=BuildArtifactResponse,
)
async def build_project_skill_artifact(
    project_id: str,
    skill_id: str,
    data: BuildArtifactRequest,
    user_id: str = Depends(get_current_user_id),
):
    """① 云端构建产物（deploy 用）：返回 contents+resources+repoHash+abstractSnapshot，
    **不写后端盘、不登记**。前端拿到后交本地代理 write-skill 落盘、算 installedHash。"""
    await _check_project_access(project_id, user_id)
    return await project_service.build_project_skill_artifact(
        project_id=project_id,
        skill_id=skill_id,
        user_id=user_id,
        tool=data.tool,
    )


@api_router.post(
    "/projects/{project_id}/skills/{skill_id}/register-deployment",
    response_model=SkillDeploymentResponse,
)
async def register_deployment(
    project_id: str,
    skill_id: str,
    data: RegisterDeploymentRequest,
    user_id: str = Depends(get_current_user_id),
):
    """④ 登记部署元数据（deploy 用）：本地代理落盘+算 installedHash 后调用，
    云端据上报 hash/snapshot UPSERT UserSkillDeployment + 写 change log，**不读后端盘**。"""
    await _check_project_access(project_id, user_id)
    return await project_service.register_deployment(
        project_id=project_id,
        skill_id=skill_id,
        user_id=user_id,
        tool=data.tool,
        deploy_path=data.deploy_path,
        install_path=data.install_path,
        installed_hash=data.installed_hash,
        repo_hash=data.repo_hash,
        repo_version=data.repo_version,
        abstract_snapshot=data.abstract_snapshot,
        overwrite=data.overwrite,
    )


@api_router.get(
    "/skill-deployments/mine",
    response_model=UserSkillDeploymentListResponse,
)
async def list_my_deployments(
    user_id: str = Depends(get_current_user_id),
):
    """列出当前用户跨项目的部署实例，供 CLI/status 与 deployment 寻址。"""
    deployments = await project_service.list_user_deployments(user_id)
    return {"success": True, "deployments": deployments}


@api_router.delete("/skill-deployments/{deployment_id}")
async def stop_tracking_deployment(
    deployment_id: str,
    delete_files: bool = Query(False),
    user_id: str = Depends(get_current_user_id),
):
    return await project_service.stop_tracking_deployment(
        deployment_id,
        user_id,
        delete_files=delete_files,
    )


@api_router.post("/skill-deployments/{deployment_id}/resume-tracking")
async def resume_tracking_deployment(
    deployment_id: str,
    data: Optional[ResumeTrackingRequest] = Body(default=None),
    user_id: str = Depends(get_current_user_id),
):
    """恢复跟踪：对已停止跟踪的部署就地重启跟踪（复用本地文件、重算基线/状态）。

    编排（桌面）形态：请求体携 `installedHash`（本地代理对 install_path 实算）；
    web 灰度形态：可无请求体，后端读 install_path 计算。本地缺失返回 status=missing。
    """
    return await project_service.resume_tracking_deployment(
        deployment_id,
        user_id,
        installed_hash=data.installed_hash if data else None,
    )


@api_router.post(
    "/skill-deployments/{deployment_id}/promote",
    response_model=SkillDeploymentResponse,
)
async def promote_deployment(
    deployment_id: str,
    user_id: str = Depends(get_current_user_id),
):
    return await project_service.promote_deployment(deployment_id, user_id)


@api_router.post(
    "/skill-deployments/{deployment_id}/push",
    response_model=PushDeploymentResponse,
)
async def push_deployment(
    deployment_id: str,
    data: Optional[PushContentRequest] = Body(default=None),
    create_version: bool = Query(False),
    version_label: str = Query(""),
    user_id: str = Depends(get_current_user_id),
):
    """推送本地改动到团队仓库。

    灰度并存（按请求体分流，路径同 M0 §9 契约）：
    - **有请求体**（`{currentHash, files}`）= 编排形态（cloud/桌面）：前端经本地代理
      read-folder 上传 install 内容，云端解析+diff+提升，**不读后端盘**。
    - **无请求体** = 一次性形态（local）：云端读 install_path 解析（维持现状）。

    `create_version`/`version_label`（query，请求体形态亦可由 body 携带）：用户选择
    "更新版本序列号"时推送成功后落一条版本快照。query 优先于 body 以兼容两种形态。
    """
    if data is not None:
        return await project_service.push_deployment_content(
            deployment_id,
            user_id,
            current_hash=data.current_hash,
            files=[f.model_dump() for f in data.files],
            create_version=create_version or data.create_version,
            version_label=version_label or data.version_label,
        )
    return await project_service.push_deployment(
        deployment_id,
        user_id,
        create_version=create_version,
        version_label=version_label,
    )


@api_router.get(
    "/skill-deployments/{deployment_id}/local-status",
    response_model=DeploymentLocalStatusResponse,
)
async def deployment_local_status(
    deployment_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """[一次性端点 · 灰度保留] 云端读 install_path 算 hash 比对。

    编排形态下，本地 hash 由本地代理 /local/hash 上报，dirty 判定不再读后端盘。"""
    return await project_service.get_deployment_local_status(deployment_id, user_id)


@api_router.post(
    "/skill-deployments/{deployment_id}/pull-update",
    response_model=PullUpdateResponse,
)
async def pull_update_deployment(
    deployment_id: str,
    data: PullUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    """[一次性端点 · 灰度保留] 云端构建+写后端盘+登记，供 local 形态使用。

    编排形态改用 build-artifact（取产物）+ 本地代理 write-skill 覆盖落盘 + commit-pull。"""
    return await project_service.pull_update_deployment(
        deployment_id, user_id, overwrite=data.overwrite
    )


# --- M4 编排：pull 拆段（build-artifact 取产物 → 本地代理覆盖落盘 → commit-pull 登记）---

@api_router.post(
    "/skill-deployments/{deployment_id}/build-artifact",
    response_model=BuildArtifactResponse,
)
async def build_deployment_artifact(
    deployment_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """① 云端构建产物（pull 用）：返回团队仓库最新 contents+resources+repoHash+
    abstractSnapshot 供前端覆盖落盘，**不写后端盘**。归属由部署实例 user_id 校验。"""
    return await project_service.build_deployment_artifact(deployment_id, user_id)


@api_router.post(
    "/skill-deployments/{deployment_id}/commit-pull",
    response_model=PullUpdateResponse,
)
async def commit_pull(
    deployment_id: str,
    data: CommitPullRequest,
    user_id: str = Depends(get_current_user_id),
):
    """拉取提交（pull 用）：覆盖落盘后登记同步状态、写 change log、广播 skill.pulled，
    **不读后端盘**（installedHash 由本地代理上报）。"""
    return await project_service.commit_pull(
        deployment_id,
        user_id,
        installed_hash=data.installed_hash,
        repo_hash=data.repo_hash,
        repo_version=data.repo_version,
        abstract_snapshot=data.abstract_snapshot,
    )


# ------------------------------------------------------------------
# AI 辅助合并（冲突一键合并），设计见 docs/design/ai-assisted-merge.md
# ------------------------------------------------------------------

@api_router.post(
    "/skill-deployments/{deployment_id}/merge-preview",
    response_model=MergePreviewResponse,
)
async def merge_preview(
    deployment_id: str,
    data: PushContentRequest,
    user_id: str = Depends(get_current_user_id),
):
    """AI 合并预览：上传本地 install 内容，云端取 base/theirs 做三方合并并返回可编辑
    合并稿（只算不写）。"""
    return await project_service.merge_preview(
        deployment_id,
        user_id,
        current_hash=data.current_hash,
        files=[f.model_dump() for f in data.files],
    )


@api_router.post(
    "/skill-deployments/{deployment_id}/merge-apply",
    response_model=MergeApplyResponse,
)
async def merge_apply(
    deployment_id: str,
    data: MergeApplyRequest,
    user_id: str = Depends(get_current_user_id),
):
    """AI 合并提交：乐观锁校验后把合并稿写回团队仓库（version+1），返回 native 构建
    产物供前端覆盖落盘。"""
    return await project_service.merge_apply(
        deployment_id,
        user_id,
        files=[f.model_dump() for f in data.files],
        merged=data.merged.model_dump(),
        expected_theirs_hash=data.expected_theirs_hash,
    )


@api_router.post(
    "/skill-deployments/{deployment_id}/commit-merge",
    response_model=PullUpdateResponse,
)
async def commit_merge(
    deployment_id: str,
    data: CommitMergeRequest,
    user_id: str = Depends(get_current_user_id),
):
    """AI 合并提交登记：覆盖落盘后置 synced、写动态(merged)、标记他人 outdated、广播。"""
    return await project_service.commit_merge(
        deployment_id,
        user_id,
        installed_hash=data.installed_hash,
        repo_hash=data.repo_hash,
        repo_version=data.repo_version,
        abstract_snapshot=data.abstract_snapshot,
    )


# ------------------------------------------------------------------
# 同步
# ------------------------------------------------------------------

@api_router.get(
    "/projects/{project_id}/sync/status", response_model=SyncStatusResponse
)
async def sync_status(
    project_id: str, user_id: str = Depends(get_current_user_id)
):
    await _check_project_access(project_id, user_id)
    skills = await project_service.get_sync_status(project_id)
    return {"success": True, "skills": skills}


@api_router.get(
    "/projects/{project_id}/sync/changes", response_model=SyncChangesResponse
)
async def sync_changes(
    project_id: str,
    since_version: int = Query(0),
    user_id: str = Depends(get_current_user_id),
):
    await _check_project_access(project_id, user_id)
    changes = await project_service.get_changes_since(project_id, since_version)
    return {"success": True, "changes": changes}


@api_router.post(
    "/projects/{project_id}/sync/pull", response_model=SyncPullResponse
)
async def sync_pull(
    project_id: str,
    data: SyncPullRequest,
    user_id: str = Depends(get_current_user_id),
):
    """批量从抽象层拉取指定 Skill 的最新内容"""
    await _check_project_access(project_id, user_id)
    items = []
    for sid in data.skill_ids:
        detail = await NativeSkillStore.get_by_id(sid)
        if not detail:
            continue
        items.append(SyncPullItem(
            skill_id=sid,
            config=detail.get("config", {}),
            vibeh_content=detail.get("vibeh_content", ""),
            version=detail.get("db", {}).get("version", 0) if detail.get("db") else 0,
            content_hash="",
        ))
    return {"success": True, "skills": items}
