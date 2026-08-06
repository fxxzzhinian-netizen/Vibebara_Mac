import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from app.api.auth import get_current_user_id
from app.core.database import async_session_factory
from app.models.skill_package import PersonalSkill, TeamSkill
from app.models.team import TeamMember
from app.schemas.project import BuildArtifactRequest, BuildArtifactResponse
from app.schemas.skill_forge import (
    ImportContentRequest,
    ImportUrlRequest,
    ImportUrlResponse,
    ImportUrlScanRequest,
    ImportUrlScanResponse,
    NativeSkillListResponse,
    NativeSkillDetailResponse,
    NativeSkillCreateRequest,
    NativeSkillUpdateRequest,
    NativeSkillImportRequest,
    NativeSkillBuildRequest,
    NativeSkillDeployRequest,
    NativeSkillMutationResponse,
    NativeSkillDeployResponse,
    NativeSkillPreviewResponse,
    SkillVersionListResponse,
    SkillVersionDetailResponse,
    RestoreVersionResponse,
)
from app.services import project_service, skill_url_import
from app.services.native_skill_store import NativeSkillStore
from app.services.skill_version_service import SkillVersionService

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/skill-forge/store", tags=["skill-store"])


async def _user_team_ids(user_id: str) -> list[str]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(TeamMember.team_id).where(TeamMember.user_id == user_id)
        )
        return list(result.scalars().all())


async def _assert_skill_accessible(skill_id: str, user_id: str) -> None:
    """归属守卫（M2 多租户补漏）。

    build / preview / complete 原先仅凭 skill_id 操作，缺少归属校验，存在跨用户
    读取/构建他人**私有 Skill** 产物或触发其 LLM 调用的越权风险（IDOR）。
    复用 NativeSkillStore.get_by_id(user_id=...) 的归属判定（personal 且非本人
    owner → 返回 None），口径与 get_skill 端点一致；不存在或无权一律拒绝。
    """
    detail = await NativeSkillStore.get_by_id(skill_id, user_id=user_id)
    if detail is None:
        raise PermissionError(f"Skill '{skill_id}' not found or access denied")


# LLM 测试（放在 /{skill_id} 之前避免路由冲突）
@api_router.get("/llm/test")
async def test_llm(user_id: str = Depends(get_current_user_id)):
    """测试 LLM API 连通性"""
    from app.services.llm_service import test_connection
    return await test_connection()


@api_router.get("/list", response_model=NativeSkillListResponse)
async def list_skills(
    scope: str = "personal",
    user_id: str = Depends(get_current_user_id),
):
    try:
        if scope == "team":
            team_ids = await _user_team_ids(user_id)
            skills = await NativeSkillStore.list_all(scope="team", team_ids=team_ids)
        else:
            skills = await NativeSkillStore.list_all(
                scope="personal", owner_id=user_id
            )
        return {"success": True, "skills": skills}
    except Exception as e:
        logger.exception("[store/list] 获取列表失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{skill_id}", response_model=NativeSkillDetailResponse)
async def get_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        detail = await NativeSkillStore.get_by_id(skill_id, user_id=user_id)
        if detail is None:
            return {"success": False, "error": f"Skill '{skill_id}' not found"}
        return {"success": True, **detail}
    except Exception as e:
        logger.exception(f"[store/get] {skill_id} 加载失败")
        raise HTTPException(status_code=500, detail=str(e))


class ResourceFileResponse(BaseModel):
    success: bool
    path: str = ""
    encoding: str = "utf8"  # utf8 | base64
    content: str = ""
    size: int = 0
    is_binary: bool = False
    error: Optional[str] = None


class ResourceFileWriteRequest(BaseModel):
    path: str
    content: str = ""
    encoding: str = "utf8"  # utf8 | base64


class ResourceFileWriteResponse(BaseModel):
    success: bool
    path: str = ""
    content_hash: str = ""
    error: Optional[str] = None


@api_router.get("/{skill_id}/resource-file", response_model=ResourceFileResponse)
async def read_resource_file(
    skill_id: str, path: str,
    user_id: str = Depends(get_current_user_id),
):
    """读取单个资源文件（scripts/references/assets/**）的真实内容。"""
    try:
        data = await NativeSkillStore.read_resource_file(skill_id, path, user_id=user_id)
        return {"success": True, **data}
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/resource-file:get] {skill_id} 读取失败: {path}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.put("/{skill_id}/resource-file", response_model=ResourceFileWriteResponse)
async def write_resource_file(
    skill_id: str, data: ResourceFileWriteRequest,
    user_id: str = Depends(get_current_user_id),
):
    """保存单个资源文件内容到对象存储（COS）。"""
    try:
        # 团队（平台）仓库 Skill：仅团队成员可编辑。
        async with async_session_factory() as session:
            team_row = await session.get(TeamSkill, skill_id)
        if team_row is not None:
            team_ids = await _user_team_ids(user_id)
            if team_row.team_id not in team_ids:
                return {"success": False, "error": "无权编辑该团队 Skill（非团队成员）"}

        result = await NativeSkillStore.write_resource_file(
            skill_id, data.path, data.content,
            encoding=data.encoding, user_id=user_id,
        )
        return {"success": True, **result}
    except (PermissionError, FileNotFoundError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/resource-file:put] {skill_id} 保存失败: {data.path}")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/create", response_model=NativeSkillMutationResponse)
async def create_skill(
    data: NativeSkillCreateRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        if "name" not in data.config:
            raise ValueError("config must contain 'name'")
        skill = await NativeSkillStore.create(
            data.config, data.vibeh_content, owner_id=user_id
        )
        return {"success": True, "skill": skill}
    except ValueError as e:
        logger.warning(f"[store/create] 参数错误: {e}")
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("[store/create] 创建失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.put("/{skill_id}", response_model=NativeSkillMutationResponse)
async def update_skill(
    skill_id: str, data: NativeSkillUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        # 团队（平台）仓库 Skill：任意团队成员均可编辑，非成员拒绝。
        async with async_session_factory() as session:
            team_row = await session.get(TeamSkill, skill_id)
        if team_row is not None:
            team_ids = await _user_team_ids(user_id)
            if team_row.team_id not in team_ids:
                return {
                    "success": False,
                    "error": "无权编辑该团队 Skill（非团队成员）",
                }

        result = await NativeSkillStore.update(
            skill_id, data.partial, vibeh_content=data.vibeh_content, user_id=user_id,
            create_version=data.create_version,
            version_number=data.version_number,
            version_label=data.version_label,
        )
        return {
            "success": True,
            "skill": result.get("skill"),
            "no_change": result.get("no_change", False),
            "diff_summary": result.get("diff_summary", ""),
            "change_items": result.get("change_items", []),
            "version": result.get("version"),
        }
    except FileNotFoundError as e:
        logger.warning(f"[store/update] {skill_id} 不存在")
        return {"success": False, "error": str(e)}
    except PermissionError as e:
        return {"success": False, "error": str(e)}
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/update] {skill_id} 更新失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.delete("/{skill_id}")
async def delete_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    try:
        # 团队（平台）仓库 Skill：任意团队成员均可删除，非成员拒绝。
        async with async_session_factory() as session:
            team_row = await session.get(TeamSkill, skill_id)
        if team_row is not None:
            team_ids = await _user_team_ids(user_id)
            if team_row.team_id not in team_ids:
                return {
                    "success": False,
                    "error": "无权删除该团队 Skill（非团队成员）",
                }

        await NativeSkillStore.delete(skill_id, user_id=user_id)
        return {"success": True}
    except PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/delete] {skill_id} 删除失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/import", response_model=NativeSkillMutationResponse)
async def import_skill(
    data: NativeSkillImportRequest,
    user_id: str = Depends(get_current_user_id),
):
    """[一次性端点 · 灰度保留] 云端读 source_path（后端盘）解析导入，供 local 形态使用。"""
    try:
        skill = await NativeSkillStore.import_from_external(
            data.source_path, data.origin, owner_id=user_id
        )
        return {"success": True, "skill": skill}
    except Exception as e:
        logger.exception(f"[store/import] 导入失败: {data.source_path}")
        return {"success": False, "error": str(e)}


@api_router.post("/import-content", response_model=NativeSkillMutationResponse)
async def import_skill_content(
    data: ImportContentRequest,
    user_id: str = Depends(get_current_user_id),
):
    """方案 B · M4 编排端点：按上传的 files[] 导入（薄代理，**云端不读后端盘**）。

    前端经本地代理 read-folder 读取本地 skill 文件夹后上传 files[]，云端写临时目录
    后复用既有 import_from_external 解析落 Store。scope=team 需团队成员校验。
    """
    try:
        scope = (data.scope or "personal").lower()
        if scope == "team":
            if not data.team_id:
                return {"success": False, "error": "scope=team 时必须提供 team_id"}
            if data.team_id not in await _user_team_ids(user_id):
                return {"success": False, "error": "无权导入到该团队（非团队成员）"}
        skill = await NativeSkillStore.import_from_content(
            [f.model_dump() for f in data.files],
            origin=data.origin,
            owner_id=user_id,
            scope=scope,
            team_id=data.team_id,
        )
        return {"success": True, "skill": skill}
    except (FileNotFoundError, ValueError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception("[store/import-content] 按内容导入失败")
        return {"success": False, "error": str(e)}


@api_router.post("/import-url/scan", response_model=ImportUrlScanResponse)
async def scan_url_skills(
    data: ImportUrlScanRequest,
    user_id: str = Depends(get_current_user_id),
):
    """解析远程链接（GitHub/Gitee/GitLab 仓库或归档 URL），返回可导入的 Skill 列表。

    全局可复用：个人 / 团队仓库共用同一解析逻辑（落库时再按 scope 分流）。
    服务端下载源到临时缓存并按 token 索引，前端勾选后调用 /import-url 落库。
    """
    try:
        result = await skill_url_import.scan_url(data.url)
        return {
            "success": True,
            "token": result["token"],
            "packages": result["packages"],
            "source_url": result.get("source_url", ""),
        }
    except (FileNotFoundError, ValueError) as e:
        return {"success": False, "packages": [], "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/import-url/scan] 解析链接失败: {data.url}")
        return {"success": False, "packages": [], "error": str(e)}


@api_router.post("/import-url", response_model=ImportUrlResponse)
async def import_url_skills(
    data: ImportUrlRequest,
    user_id: str = Depends(get_current_user_id),
):
    """把链接解析结果中勾选的 Skill 导入到个人 / 团队仓库（全局，scope 分流）。"""
    scope = (data.scope or "personal").lower()
    if scope == "team":
        if not data.team_id:
            return {"success": False, "error": "scope=team 时必须提供 team_id"}
        if data.team_id not in await _user_team_ids(user_id):
            return {"success": False, "error": "无权导入到该团队（非团队成员）"}
    if not data.source_paths:
        return {"success": False, "error": "未选择要导入的 Skill"}

    results = []
    skills = []
    ok = 0
    try:
        for rel in data.source_paths:
            try:
                src = skill_url_import.resolve_in_cache(data.token, rel)
                if scope == "team":
                    skill = await NativeSkillStore.import_external_to_team(
                        str(src), data.team_id, user_id,
                        source_url=data.source_url,
                    )
                else:
                    skill = await NativeSkillStore.import_from_external(
                        str(src), owner_id=user_id, source_url=data.source_url,
                    )
                ok += 1
                skills.append(skill)
                results.append({"source_path": rel, "success": True, "skill": skill})
            except (FileNotFoundError, ValueError, PermissionError) as e:
                results.append({"source_path": rel, "success": False, "error": str(e)})
            except Exception as e:  # noqa: BLE001
                logger.exception(f"[store/import-url] 导入失败: {rel}")
                results.append({"source_path": rel, "success": False, "error": str(e)})
    finally:
        # 全部尝试完毕后释放缓存（无论成败，避免占用磁盘）。
        skill_url_import.discard(data.token)

    return {
        "success": ok > 0,
        "imported": ok,
        "skills": skills,
        "results": results,
        "error": None if ok > 0 else "导入失败，请查看各项错误",
    }


@api_router.post("/{skill_id}/complete")
async def complete_skill(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """调用 LLM 为缺失字段生成建议值，返回给前端供用户确认"""
    try:
        await _assert_skill_accessible(skill_id, user_id)
        result = await NativeSkillStore.complete_fields(skill_id)
        return {"success": True, **result}
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/complete] {skill_id} 补齐失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/{skill_id}/tags/generate")
async def generate_skill_tags(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """调用 LLM 从固定词表为该 Skill 重新生成标签并落库，返回最终标签。

    供卡片上「重新生成标签」等手动触发使用；force=True 覆盖已有标签。
    """
    try:
        await _assert_skill_accessible(skill_id, user_id)
        tags = await NativeSkillStore.regenerate_tags(skill_id, force=True)
        return {"success": True, "tags": tags}
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/tags] {skill_id} 标签生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/{skill_id}/intro/generate")
async def generate_skill_intro(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """调用 LLM 根据该 Skill 内容生成「介绍页」草稿（不落库），供编辑页 AI 辅助填写。

    返回 {success, draft:{title, category, short_description, intro_md}}；
    LLM 未配置/失败/无内容时返回 {success:False, error}，由前端回退手填。
    """
    from app.services.llm_service import generate_skill_intro as _gen_intro

    try:
        await _assert_skill_accessible(skill_id, user_id)
        detail = await NativeSkillStore.get_by_id(skill_id, user_id=user_id)
        if detail is None:
            return {"success": False, "error": f"Skill '{skill_id}' not found"}
        config = detail.get("config") or {}
        db = detail.get("db") or {}
        tags = db.get("tags") or config.get("metadata", {}).get("tags", []) or []
        draft = await _gen_intro(
            name=config.get("name") or skill_id,
            description=config.get("description", "") or "",
            body_preview=detail.get("vibeh_content", "") or "",
            tags=tags,
        )
        if not draft:
            return {
                "success": False,
                "error": "AI 未返回内容（可能未配置模型或调用失败），可手动填写。",
            }
        return {"success": True, "draft": draft}
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/intro] {skill_id} 介绍生成失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/{skill_id}/build")
async def build_skill(
    skill_id: str, data: NativeSkillBuildRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        await _assert_skill_accessible(skill_id, user_id)
        result = await NativeSkillStore.build(skill_id, data.target)
        return result
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/build] {skill_id} 构建失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post(
    "/{skill_id}/build-artifact",
    response_model=BuildArtifactResponse,
)
async def build_store_skill_artifact(
    skill_id: str, data: BuildArtifactRequest,
    user_id: str = Depends(get_current_user_id),
):
    """方案 B · M4 编排端点（store 级）：个人/团队仓库 Skill 构建产物。

    对应前端 deployNativeSkillOrchestrated。返回 contents(文本)+resources(base64
    inline)+repoHash+abstractSnapshot，**不写后端盘**。归属守卫复用 build/deploy 口径
    （IDOR 防护）。契约 §9 未单列 store 级 build-artifact，本端点补齐并与前端对齐。
    """
    try:
        await _assert_skill_accessible(skill_id, user_id)
        return await project_service.build_store_skill_artifact(
            skill_id, user_id, data.tool
        )
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/build-artifact] {skill_id} 构建产物失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/{skill_id}/deploy", response_model=NativeSkillDeployResponse)
async def deploy_skill(
    skill_id: str, data: NativeSkillDeployRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        await _assert_skill_accessible(skill_id, user_id)
        result = await NativeSkillStore.deploy(
            skill_id, data.target, dest_path=data.dest_path, user_id=user_id
        )
        return result
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except PermissionError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/deploy] {skill_id} 部署失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/{skill_id}/preview", response_model=NativeSkillPreviewResponse)
async def preview_skill(
    skill_id: str, target: str = "all",
    user_id: str = Depends(get_current_user_id),
):
    try:
        await _assert_skill_accessible(skill_id, user_id)
        result = await NativeSkillStore.preview(skill_id, target)
        return result
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/preview] {skill_id} 预览失败")
        raise HTTPException(status_code=500, detail=str(e))


# =========================================================================
# Skill 版本记录（团队仓库版本快照：列表 / 查看 / 回滚）
# =========================================================================


async def _assert_team_skill_editable(skill_id: str, user_id: str) -> None:
    """版本回滚等写操作的鉴权：团队 Skill 需团队成员；个人 Skill 需本人。"""
    async with async_session_factory() as session:
        team_row = await session.get(TeamSkill, skill_id)
        personal_row = None if team_row else await session.get(PersonalSkill, skill_id)
    if team_row is not None:
        if team_row.team_id not in await _user_team_ids(user_id):
            raise PermissionError("无权操作该团队 Skill（非团队成员）")
    elif personal_row is not None:
        if personal_row.owner_id and personal_row.owner_id != user_id:
            raise PermissionError("无权操作他人的个人 Skill")
    else:
        raise FileNotFoundError(f"Skill '{skill_id}' not found")


@api_router.get("/{skill_id}/versions", response_model=SkillVersionListResponse)
async def list_skill_versions(
    skill_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """列出该 Skill 的所有版本快照（按序列号倒序）。"""
    try:
        await _assert_skill_accessible(skill_id, user_id)
        versions = await SkillVersionService.list_versions(skill_id)
        return {"success": True, "versions": versions}
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/versions] {skill_id} 版本列表失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get(
    "/{skill_id}/versions/{version_id}",
    response_model=SkillVersionDetailResponse,
)
async def get_skill_version(
    skill_id: str, version_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """查看某个历史版本的完整内容（config + SKILL 正文）。"""
    try:
        await _assert_skill_accessible(skill_id, user_id)
        version = await SkillVersionService.get_version(version_id)
        if version is None or version.get("skill_id") != skill_id:
            return {"success": False, "error": "版本不存在"}
        return {"success": True, "version": version}
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/versions] {skill_id}/{version_id} 查看失败")
        raise HTTPException(status_code=500, detail=str(e))


class VersionResourceFileResponse(BaseModel):
    success: bool
    path: str = ""
    change: str = ""
    seq: Optional[int] = None
    version_number: str = ""
    prev_version_id: Optional[str] = None
    prev_seq: Optional[int] = None
    prev_version_number: Optional[str] = None
    new: Optional[Dict[str, Any]] = None
    old: Optional[Dict[str, Any]] = None
    diff: str = ""
    diff_truncated: bool = False
    error: Optional[str] = None


@api_router.get(
    "/{skill_id}/versions/{version_id}/resource-file",
    response_model=VersionResourceFileResponse,
)
async def read_version_resource_file(
    skill_id: str, version_id: str, path: str,
    user_id: str = Depends(get_current_user_id),
):
    """读取某版本快照中的单个资源文件内容（含与上一版本的 unified diff）。"""
    try:
        await _assert_skill_accessible(skill_id, user_id)
        data = await SkillVersionService.get_resource_file(
            skill_id, version_id, path
        )
        if data is None:
            return {"success": False, "error": "版本不存在"}
        return {"success": True, **data}
    except (FileNotFoundError, PermissionError, ValueError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(
            f"[store/versions] {skill_id}/{version_id} 资源文件读取失败: {path}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post(
    "/{skill_id}/versions/{version_id}/restore",
    response_model=RestoreVersionResponse,
)
async def restore_skill_version(
    skill_id: str, version_id: str,
    user_id: str = Depends(get_current_user_id),
):
    """把团队仓库内容回滚到指定历史版本（会生成一个新的 restore 版本）。"""
    try:
        await _assert_team_skill_editable(skill_id, user_id)
        result = await SkillVersionService.restore_version(
            skill_id, version_id, user_id
        )
        return {
            "success": True,
            "version": result.get("version"),
            "diff_summary": result.get("diff_summary", ""),
        }
    except (FileNotFoundError, PermissionError) as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[store/versions] {skill_id}/{version_id} 回滚失败")
        raise HTTPException(status_code=500, detail=str(e))
