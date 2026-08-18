import asyncio
import hashlib
import json
import logging
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy import case, delete, func, select

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.device import Device
from app.models.project import Project, ProjectSkill, UserSkillDeployment
from app.models.skill_change_log import SkillChangeLog
from app.models.skill_package import PersonalSkill, TeamSkill
from app.models.team import Team, TeamMember
from app.models.user import User
from app.services.content_transfer import (
    build_install_tree,
    collect_store_resources,
    write_files,
)
from app.services.native_skill_store import NativeSkillStore
from app.services.skill_diff_service import (
    diff_abstract_packages,
    parse_native_skill,
    summarize_changes,
)
from app.services.team_sync_service import TeamSyncService

logger = logging.getLogger(__name__)
_skill_write_locks: Dict[str, asyncio.Lock] = {}

SUPPORTED_TOOLS = {"cursor", "codex", "windsurf", "claude", "kiro", "trae", "qoder", "workbuddy"}
GITIGNORE_BLOCK = [
    "# Vibebara local skill deployments",
    ".cursor/skills/",
    ".codex/skills/",
    ".windsurf/skills/",
    ".claude/skills/",
    ".kiro/skills/",
    ".trae/skills/",
    ".qoder/skills/",
    ".workbuddy/skills/",
]


def _skill_write_lock(skill_id: str) -> asyncio.Lock:
    return _skill_write_locks.setdefault(skill_id, asyncio.Lock())


async def _active_device_id(session, user_id: str) -> Optional[str]:
    return await session.scalar(
        select(Device.id)
        .where(Device.user_id == user_id, Device.status == "active")
        .order_by(Device.last_seen_at.desc(), Device.updated_at.desc())
        .limit(1)
    )
VIBEBARA_GUIDE_FILENAME = "vibebara.md"
VIBEBARA_GUIDE_START = "<!-- vibebara:commands:start -->"
VIBEBARA_GUIDE_END = "<!-- vibebara:commands:end -->"
VIBEBARA_GUIDE_BLOCK = f"""{VIBEBARA_GUIDE_START}
# Vibebara Skill 协作指南

此项目的 Skill 由 Vibebara 管理。请在项目根目录打开终端并执行以下命令。

## 查看部署状态

```bash
vibebara status
```

## 拉取团队最新 Skill

```bash
vibebara pull <skill-name>
```

如果需要覆盖尚未推送的本地改动：

```bash
vibebara pull <skill-name> --overwrite
```

## 推送本地改动

```bash
vibebara push <skill-name>
```

创建版本时可使用：

```bash
vibebara push <skill-name> --create-version --version-number 1.2 --version-label "版本说明"
```

## 合并冲突

先预览 AI 三方合并结果：

```bash
vibebara merge <skill-name> --preview
```

确认后执行合并：

```bash
vibebara merge <skill-name>
```

当项目中存在多个同名部署时，可增加 `--project <project-id>` 或
`--deployment <deployment-id>` 精确指定。使用 `vibebara <command> --help`
查看完整参数。

{VIBEBARA_GUIDE_END}
"""


def _project_to_dict(
    project: Project,
    skill_count: int = 0,
    pending_commit_count: int = 0,
    pending_update_count: int = 0,
    last_commit_at: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": project.id,
        "team_id": project.team_id,
        "name": project.name,
        "description": project.description,
        "created_by": project.created_by,
        "skill_count": skill_count,
        "pending_commit_count": pending_commit_count,
        "pending_update_count": pending_update_count,
        "last_commit_at": last_commit_at,
        "created_at": project.created_at.isoformat() if project.created_at else None,
        "updated_at": project.updated_at.isoformat() if project.updated_at else None,
    }


def _compute_store_hash(prefix: str) -> str:
    """对象存储前缀内容哈希。

    用于平台 Store 内容（store_path 现为对象键前缀）；与 `_compute_content_hash`
    （本地 install 目录）同口径，仅数据来源改为对象列举。
    """
    if not prefix:
        return ""
    from app.services.object_store import get_object_store

    return get_object_store().compute_prefix_hash(prefix)


def _compute_content_hash(store_path: str) -> str:
    # R2 收敛（M0 §7.2）：排序键统一为「相对 root 的 POSIX 路径字符串的
    # UTF-8 字节序」，大小写敏感、不做 normcase、分隔符恒为 '/'。
    # 必须与 native_skill_store / 本地代理位级一致，否则跨平台/中文名会导致 dirty 误判。
    # 注：本函数仅用于**本地 install 目录**；平台 Store（对象存储前缀）用 _compute_store_hash。
    root = Path(store_path)
    if not root.exists():
        return ""

    digest = hashlib.sha256()
    has_files = False
    files = sorted(
        (p for p in root.rglob("*") if p.is_file()),
        key=lambda p: p.relative_to(root).as_posix().encode("utf-8"),
    )
    for file_path in files:
        rel = file_path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_path.read_bytes())
        digest.update(b"\0")
        has_files = True
    return digest.hexdigest() if has_files else ""


def _install_root(deploy_path: str, tool_type: str) -> Path:
    root = Path(deploy_path)
    if tool_type == "cursor":
        return root / ".cursor" / "skills"
    if tool_type == "codex":
        return root / ".codex" / "skills"
    if tool_type == "windsurf":
        return root / ".windsurf" / "skills"
    if tool_type == "claude":
        return root / ".claude" / "skills"
    if tool_type == "kiro":
        return root / ".kiro" / "skills"
    if tool_type == "trae":
        return root / ".trae" / "skills"
    if tool_type == "qoder":
        return root / ".qoder" / "skills"
    if tool_type == "workbuddy":
        return root / ".workbuddy" / "skills"
    raise ValueError("tool_type must be cursor, codex, windsurf, claude, kiro, trae, qoder or workbuddy")


def _ensure_gitignore(project_root: str) -> None:
    root = Path(project_root)
    root.mkdir(parents=True, exist_ok=True)
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    lines = existing.splitlines()
    missing = [line for line in GITIGNORE_BLOCK if line not in lines]
    if not missing:
        return

    prefix = "\n" if existing and not existing.endswith("\n") else ""
    block = "\n".join(missing)
    suffix = "\n" if not block.endswith("\n") else ""
    gitignore.write_text(f"{existing}{prefix}{block}{suffix}", encoding="utf-8")


def _ensure_vibebara_guide(project_root: str) -> None:
    """写入命令行协作指南；保留用户内容，仅维护 Vibebara 标记区块。"""
    root = Path(project_root)
    root.mkdir(parents=True, exist_ok=True)
    guide_path = root / VIBEBARA_GUIDE_FILENAME
    existing = guide_path.read_text(encoding="utf-8") if guide_path.exists() else ""

    start = existing.find(VIBEBARA_GUIDE_START)
    end = existing.find(VIBEBARA_GUIDE_END, start)
    if start >= 0 and end >= start:
        suffix_start = end + len(VIBEBARA_GUIDE_END)
        updated = (
            existing[:start]
            + VIBEBARA_GUIDE_BLOCK.rstrip()
            + existing[suffix_start:]
        )
        if not updated.endswith("\n"):
            updated += "\n"
    else:
        if not existing:
            separator = ""
        elif existing.endswith("\n\n"):
            separator = ""
        elif existing.endswith("\n"):
            separator = "\n"
        else:
            separator = "\n\n"
        updated = f"{existing}{separator}{VIBEBARA_GUIDE_BLOCK}"

    if updated != existing:
        guide_path.write_text(updated, encoding="utf-8")


def _deployment_to_dict(row: Optional[UserSkillDeployment]) -> Optional[Dict[str, Any]]:
    if not row:
        return None
    return {
        "id": row.id,
        "user_id": row.user_id,
        "device_id": row.device_id,
        "project_id": row.project_id,
        "team_skill_id": row.team_skill_id,
        "skill_name": row.skill_name,
        "tool_type": row.tool_type,
        "deploy_path": row.deploy_path,
        "install_path": row.install_path,
        "repo_version": row.repo_version,
        "repo_hash": row.repo_hash,
        "installed_hash": row.installed_hash,
        "status": row.status,
        "tracking_enabled": row.tracking_enabled,
        "local_dirty": row.local_dirty,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def _write_change_log(
    *,
    session,
    team_id: Optional[str],
    project_id: Optional[str],
    deployment_id: Optional[str],
    skill_id: str,
    user_id: str,
    action: str,
    version: int,
    diff_summary: str = "",
    source: str = "user_deployment",
    base_hash: str = "",
    new_hash: str = "",
    change_items: Optional[List[Dict[str, Any]]] = None,
) -> None:
    session.add(
        SkillChangeLog(
            team_id=team_id,
            project_id=project_id,
            deployment_id=deployment_id,
            skill_id=skill_id,
            user_id=user_id,
            action=action,
            version=version,
            diff_summary=diff_summary,
            source=source,
            base_hash=base_hash,
            new_hash=new_hash,
            change_items=json.dumps(change_items or [], ensure_ascii=False),
        )
    )


# ------------------------------------------------------------------
# Project CRUD
# ------------------------------------------------------------------


async def create_project(
    team_id: str, name: str, description: str, created_by: str
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        project = Project(
            team_id=team_id,
            name=name,
            description=description,
            created_by=created_by,
        )
        session.add(project)
        await session.commit()
        await session.refresh(project)
        result = _project_to_dict(project, skill_count=0)

    # 团队级实时同步：通知在线成员刷新项目列表（无需手动刷新）
    await TeamSyncService.emit_project_created(team_id, result, created_by)
    return result


async def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        if not project:
            return None
        count = await session.scalar(
            select(func.count()).select_from(ProjectSkill).where(
                ProjectSkill.project_id == project_id
            )
        )
        return _project_to_dict(project, skill_count=count or 0)


async def update_project(
    project_id: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    user_id: str = "system",
) -> Optional[Dict[str, Any]]:
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        if not project:
            return None
        team_id = project.team_id
        if name is not None:
            project.name = name
        if description is not None:
            project.description = description
        await session.commit()
        await session.refresh(project)
        count = await session.scalar(
            select(func.count()).select_from(ProjectSkill).where(
                ProjectSkill.project_id == project_id
            )
        )
        result = _project_to_dict(project, skill_count=count or 0)

    await TeamSyncService.emit_project_updated(team_id, result, user_id)
    return result


async def delete_project(project_id: str, user_id: str = "system") -> bool:
    """
    删除项目及其关联数据（动态日志、用户部署记录、Skill 关联）。

    显式清理子表，不依赖数据库外键级联，保证跨引擎一致。
    各用户本地已部署的文件分布在各自机器上，平台无法删除，保留由用户自行清理。
    """
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        if not project:
            return False
        team_id = project.team_id
        await session.execute(
            delete(SkillChangeLog).where(SkillChangeLog.project_id == project_id)
        )
        await session.execute(
            delete(UserSkillDeployment).where(
                UserSkillDeployment.project_id == project_id
            )
        )
        await session.execute(
            delete(ProjectSkill).where(ProjectSkill.project_id == project_id)
        )
        await session.delete(project)
        await session.commit()

    # 团队级实时同步：通知在线成员移除该项目卡片
    await TeamSyncService.emit_project_deleted(team_id, project_id, user_id)
    return True


async def list_projects(team_id: str, user_id: str) -> List[Dict[str, Any]]:
    """团队项目列表（含当前用户视角的卡片摘要）。

    每张卡片附带：关联 Skill 数、当前用户的「待提交」（本地有改动待推送）/
    「待更新」（团队仓库有新版本可拉取）数，以及该项目「最近一次提交（推送）」时间。
    """
    async with async_session_factory() as session:
        device_id = await _active_device_id(session, user_id)
        if not device_id:
            return []
        result = await session.execute(
            select(Project, func.count(ProjectSkill.id).label("cnt"))
            .outerjoin(ProjectSkill, ProjectSkill.project_id == Project.id)
            .where(Project.team_id == team_id)
            .group_by(Project.id)
            .order_by(Project.created_at.desc())
        )
        rows = result.all()
        project_ids = [project.id for project, _ in rows]
        if not project_ids:
            return []

        # 当前用户在各项目下的待提交 / 待更新数（按部署实例聚合）。
        # 待提交 = 本地有改动（local_dirty）；待更新 = 团队仓库有新版本（status=outdated）。
        dep_result = await session.execute(
            select(
                UserSkillDeployment.project_id,
                func.sum(
                    case((UserSkillDeployment.local_dirty.is_(True), 1), else_=0)
                ).label("pending_commit"),
                func.sum(
                    case((UserSkillDeployment.status == "outdated", 1), else_=0)
                ).label("pending_update"),
            )
            .where(
                UserSkillDeployment.user_id == user_id,
                UserSkillDeployment.device_id == device_id,
                UserSkillDeployment.project_id.in_(project_ids),
            )
            .group_by(UserSkillDeployment.project_id)
        )
        pending_map = {
            pid: (int(commit or 0), int(update or 0))
            for pid, commit, update in dep_result.all()
        }

        # 各项目最近一次「提交」（推送到团队仓库）的时间。
        commit_result = await session.execute(
            select(
                SkillChangeLog.project_id,
                func.max(SkillChangeLog.created_at).label("last_commit"),
            )
            .where(
                SkillChangeLog.project_id.in_(project_ids),
                SkillChangeLog.action == "pushed",
            )
            .group_by(SkillChangeLog.project_id)
        )
        commit_map = {pid: ts for pid, ts in commit_result.all()}

        out: List[Dict[str, Any]] = []
        for project, cnt in rows:
            commit, update = pending_map.get(project.id, (0, 0))
            last_commit = commit_map.get(project.id)
            out.append(
                _project_to_dict(
                    project,
                    skill_count=cnt or 0,
                    pending_commit_count=commit,
                    pending_update_count=update,
                    last_commit_at=last_commit.isoformat() if last_commit else None,
                )
            )
        return out


# ------------------------------------------------------------------
# Project skill refs
# ------------------------------------------------------------------


async def add_skill_to_project(
    project_id: str, skill_id: str, user_id: str
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        if not project:
            return {"success": False, "error": "Project not found"}

        pkg = await session.get(TeamSkill, skill_id)
        if not pkg:
            return {"success": False, "error": f"Skill '{skill_id}' not found（项目仅能关联团队仓库 Skill，请先「放入团队」）"}
        if pkg.team_id and pkg.team_id != project.team_id:
            return {"success": False, "error": "Skill belongs to another team"}

        existing = await session.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "Skill already added to project"}

        latest_hash = _compute_store_hash(pkg.store_path) if pkg.store_path else ""
        pkg.content_hash = latest_hash

        session.add(
            ProjectSkill(
                project_id=project_id,
                skill_id=skill_id,
                added_by=user_id,
                last_modified_by=user_id,
                version=1,
                content_hash=latest_hash,
            )
        )
        # 记入项目动态 / 审计：关联 Skill 到项目。version≥1 以通过 get_changes_since 过滤。
        await _write_change_log(
            session=session,
            team_id=project.team_id,
            project_id=project_id,
            deployment_id=None,
            skill_id=skill_id,
            user_id=user_id,
            action="linked",
            version=1,
            source="project_skill",
            new_hash=latest_hash,
        )
        await session.commit()

    await _broadcast_push_event(
        project_id=project_id,
        skill_id=skill_id,
        user_id=user_id,
        change_items=[],
        summary="",
        status="",
        event_type="skill.linked",
    )
    return {"success": True}


async def remove_skill_from_project(
    project_id: str, skill_id: str, user_id: str
) -> Dict[str, Any]:
    """从项目移除 Skill 关联。

    跟踪守卫：当前用户该 Skill 仍在跟踪（tracking_enabled=True）时拦截，要求先
    「停止跟踪」，避免移除后留下够不着的孤儿部署。移除通过后顺带删除当前用户该
    project+skill 的残留（已 untracked）部署记录，杜绝重新关联时复活错位。
    """
    async with async_session_factory() as session:
        result = await session.execute(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        ps = result.scalar_one_or_none()
        if not ps:
            return {"success": False, "error": "Project skill ref not found"}

        active = await session.scalar(
            select(UserSkillDeployment).where(
                UserSkillDeployment.project_id == project_id,
                UserSkillDeployment.team_skill_id == skill_id,
                UserSkillDeployment.user_id == user_id,
                UserSkillDeployment.tracking_enabled.is_(True),
            )
        )
        if active:
            return {
                "success": False,
                "code": "tracking_active",
                "error": "请先停止跟踪再移除",
            }

        removed_version = ps.version or 1
        project = await session.get(Project, project_id)
        team_id = project.team_id if project else None

        await session.execute(
            delete(UserSkillDeployment).where(
                UserSkillDeployment.project_id == project_id,
                UserSkillDeployment.team_skill_id == skill_id,
                UserSkillDeployment.user_id == user_id,
            )
        )
        await session.delete(ps)
        # 记入项目动态 / 审计：从项目移除 Skill 关联。version≥1 以通过 get_changes_since 过滤。
        await _write_change_log(
            session=session,
            team_id=team_id,
            project_id=project_id,
            deployment_id=None,
            skill_id=skill_id,
            user_id=user_id,
            action="unlinked",
            version=removed_version,
            source="project_skill",
        )
        await session.commit()

    await _broadcast_push_event(
        project_id=project_id,
        skill_id=skill_id,
        user_id=user_id,
        change_items=[],
        summary="",
        status="",
        event_type="skill.unlinked",
    )
    return {"success": True}


async def list_project_skills(
    project_id: str, user_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ProjectSkill, TeamSkill)
            .join(TeamSkill, TeamSkill.id == ProjectSkill.skill_id)
            .where(ProjectSkill.project_id == project_id)
            .order_by(ProjectSkill.created_at.desc())
        )
        rows = result.all()

        deployment_map: Dict[str, UserSkillDeployment] = {}
        if user_id:
            device_id = await _active_device_id(session, user_id)
            dep_result = await session.execute(
                select(UserSkillDeployment)
                .where(
                    UserSkillDeployment.project_id == project_id,
                    UserSkillDeployment.user_id == user_id,
                    UserSkillDeployment.device_id == device_id,
                )
                .order_by(UserSkillDeployment.updated_at.desc())
            )
            for dep in dep_result.scalars().all():
                deployment_map.setdefault(dep.team_skill_id, dep)

        items = []
        for ps, pkg in rows:
            items.append(
                {
                    "skill_id": ps.skill_id,
                    "display_name": pkg.display_name or pkg.name,
                    "description": pkg.description,
                    "version": ps.version,
                    "content_hash": pkg.content_hash or ps.content_hash,
                    "last_modified_by": ps.last_modified_by,
                    "updated_at": ps.updated_at.isoformat() if ps.updated_at else None,
                    "deployment": _deployment_to_dict(deployment_map.get(ps.skill_id)),
                }
            )
        return items


# ------------------------------------------------------------------
# User deployments
# ------------------------------------------------------------------


async def deploy_project_skill(
    project_id: str,
    skill_id: str,
    user_id: str,
    tool_type: str,
    deploy_path: str,
    overwrite: bool = False,
    scope: str = "project",
) -> Dict[str, Any]:
    tool_type = tool_type.lower()
    if tool_type not in SUPPORTED_TOOLS:
        return {"success": False, "error": "tool_type must be cursor, codex, windsurf, claude, kiro, trae, qoder or workbuddy"}

    # 全局部署：落本机平台目录 ~/.{tool}/skills/{自然名}，一次性安装、不登记跟踪。
    # 仍校验项目存在与 Skill 关联关系，保持与项目级部署一致的访问约束。
    if scope == "platform":
        async with async_session_factory() as session:
            project = await session.get(Project, project_id)
            pkg = await session.get(TeamSkill, skill_id)
            if not project or not pkg:
                return {"success": False, "error": "Project or skill not found"}
            ref = await session.scalar(
                select(ProjectSkill).where(
                    ProjectSkill.project_id == project_id,
                    ProjectSkill.skill_id == skill_id,
                )
            )
            if not ref:
                return {"success": False, "error": "Skill is not added to this project"}
        result = await NativeSkillStore.deploy(
            skill_id,
            tool_type,
            dest_path=None,
            notify=False,
            allow_team=True,
        )
        if not result.get("success"):
            return result
        return {"success": True, "deployed": result.get("deployed", [])}

    if not deploy_path:
        return {"success": False, "error": "deploy_path is required"}
    if not Path(deploy_path).is_dir():
        return {"success": False, "error": "deploy_path must be an existing local directory"}

    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        pkg = await session.get(TeamSkill, skill_id)
        if not project or not pkg:
            return {"success": False, "error": "Project or skill not found"}

        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        if not ref:
            return {"success": False, "error": "Skill is not added to this project"}

        install_path = _install_root(deploy_path, tool_type) / pkg.name
        if install_path.exists() and not overwrite:
            return {"success": False, "error": "Install path exists; pass overwrite=true"}

        repo_hash = _compute_store_hash(pkg.store_path) if pkg.store_path else ""
        pkg.content_hash = repo_hash
        ref.content_hash = repo_hash

    result = await NativeSkillStore.deploy(
        skill_id,
        tool_type,
        dest_path=deploy_path,
        notify=False,
        allow_team=True,
    )
    if not result.get("success"):
        return result

    _ensure_gitignore(deploy_path)
    _ensure_vibebara_guide(deploy_path)

    installed_hash = _compute_content_hash(str(install_path))
    now = datetime.now(timezone.utc)

    try:
        snapshot = parse_native_skill(str(install_path), tool_type)
        snapshot_json = json.dumps(snapshot, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"[deploy] 解析初始抽象包失败 skill='{skill_id}': {e}")
        snapshot_json = ""

    async with async_session_factory() as session:
        device_id = await _active_device_id(session, user_id)
        if not device_id:
            return {"success": False, "error": "当前登录未绑定有效设备，请重新登录"}
        project = await session.get(Project, project_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        existing = await session.scalar(
            select(UserSkillDeployment).where(
                UserSkillDeployment.user_id == user_id,
                UserSkillDeployment.device_id == device_id,
                UserSkillDeployment.project_id == project_id,
                UserSkillDeployment.team_skill_id == skill_id,
                UserSkillDeployment.tool_type == tool_type,
                UserSkillDeployment.deploy_path == str(Path(deploy_path)),
            )
        )

        deployment = existing or UserSkillDeployment(
            user_id=user_id,
            device_id=device_id,
            project_id=project_id,
            team_skill_id=skill_id,
            tool_type=tool_type,
            deploy_path=str(Path(deploy_path)),
        )
        deployment.skill_name = skill_id
        deployment.install_path = str(install_path)
        deployment.repo_version = ref.version if ref else 1
        deployment.repo_hash = ref.content_hash if ref else repo_hash
        deployment.installed_hash = installed_hash
        deployment.abstract_snapshot = snapshot_json
        deployment.status = "synced"
        deployment.tracking_enabled = True
        deployment.local_dirty = False
        deployment.last_seen_at = now
        session.add(deployment)
        await session.flush()

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="deployed",
            version=deployment.repo_version,
            diff_summary=f"deployed to {tool_type}: {deployment.install_path}",
            base_hash=deployment.repo_hash,
            new_hash=installed_hash,
        )
        await session.commit()
        await session.refresh(deployment)
        return {
            "success": True,
            "deployment": _deployment_to_dict(deployment),
            "deployed": result.get("deployed", []),
        }


async def stop_tracking_deployment(
    deployment_id: str,
    user_id: str,
    delete_files: bool = False,
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot stop another user's deployment"}

        project = await session.get(Project, deployment.project_id)
        install_path = deployment.install_path
        deployment.tracking_enabled = False
        deployment.status = "untracked"
        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=deployment.team_skill_id,
            user_id=user_id,
            action="stopped",
            version=deployment.repo_version,
            diff_summary="停止跟踪",
            base_hash=deployment.installed_hash,
            new_hash=deployment.installed_hash,
        )
        await session.commit()

    if delete_files and install_path:
        shutil.rmtree(install_path, ignore_errors=True)
    return {"success": True}


async def resume_tracking_deployment(
    deployment_id: str,
    user_id: str,
    installed_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """恢复跟踪：对已停止跟踪（untracked）的部署就地重启跟踪。

    复用现有本地文件：以本地当前 hash 重新刷新 dirty/状态，并把 repo_hash/
    repo_version 对齐团队仓库最新。基线 installed_hash **保留不覆盖**，使停跟踪
    期间的本地改动恢复为「待推送(changed)」而非静默丢弃。

    installed_hash：编排（桌面）形态由前端经本地代理实算上报（权威）；web 灰度
    形态留空，由后端读 install_path 计算。本地缺失则不启用跟踪并引导重新部署。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot resume another user's deployment"}
        if deployment.tracking_enabled:
            return {"success": False, "error": "Deployment is already tracking"}

        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        if not project or not pkg or not ref:
            return {"success": False, "error": "该 Skill 已从项目移除，无法恢复跟踪"}

        install_path = deployment.install_path
        base_installed_hash = deployment.installed_hash
        base_repo_hash = deployment.repo_hash

        # 本地当前 hash：编排上报优先，否则后端读盘
        current_local_hash = (
            installed_hash
            if installed_hash is not None
            else _compute_content_hash(install_path)
        )

        if not current_local_hash:
            deployment.status = "missing"
            deployment.local_dirty = False
            deployment.last_seen_at = datetime.now(timezone.utc)
            await session.commit()
            return {
                "success": False,
                "status": "missing",
                "error": "本地部署目录缺失，请重新部署",
            }

        team_hash = _compute_store_hash(pkg.store_path) if pkg.store_path else ""
        local_changed = current_local_hash != base_installed_hash
        repo_advanced = bool(base_repo_hash) and base_repo_hash != team_hash

        if repo_advanced and local_changed:
            new_status = "conflict"
        elif repo_advanced:
            new_status = "outdated"
        elif local_changed:
            new_status = "changed"
        else:
            new_status = "synced"

        deployment.tracking_enabled = True
        deployment.local_dirty = local_changed
        deployment.repo_hash = team_hash
        deployment.repo_version = ref.version
        deployment.status = new_status
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=deployment.team_skill_id,
            user_id=user_id,
            action="resumed",
            version=deployment.repo_version,
            diff_summary="恢复跟踪",
            base_hash=base_installed_hash,
            new_hash=current_local_hash,
        )
        await session.commit()
        await session.refresh(deployment)
        return {"success": True, "deployment": _deployment_to_dict(deployment)}


async def promote_deployment(
    deployment_id: str,
    user_id: str,
    auto: bool = False,
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if not auto and deployment.user_id != user_id:
            return {"success": False, "error": "Cannot promote another user's deployment"}

        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        if not project or not pkg or not ref:
            return {"success": False, "error": "Project skill relation missing"}

        team_hash = _compute_store_hash(pkg.store_path) if pkg.store_path else ""
        local_hash = _compute_content_hash(deployment.install_path)
        if not local_hash:
            deployment.status = "missing"
            await session.commit()
            return {"success": False, "error": "Deployment files missing"}
        if deployment.repo_hash and deployment.repo_hash != team_hash:
            deployment.status = "conflict"
            deployment.installed_hash = local_hash
            await session.commit()
            return {"success": False, "error": "Conflict: team skill changed after deployment"}

    await NativeSkillStore.import_from_external(
        deployment.install_path,
        deployment.tool_type,
        allow_team_update=True,
        target_skill_id=deployment.team_skill_id,
    )

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        promoted_hash = _compute_store_hash(pkg.store_path) if pkg and pkg.store_path else ""
        if pkg:
            # 拆表后 pkg 即团队表行，team_id 已固定，无需再翻转 scope。
            pkg.content_hash = promoted_hash
        if ref:
            ref.version += 1
            ref.content_hash = promoted_hash
            ref.last_modified_by = deployment.user_id

        try:
            promoted_snapshot = json.dumps(
                parse_native_skill(deployment.install_path, deployment.tool_type),
                ensure_ascii=False,
            )
        except Exception:
            promoted_snapshot = deployment.abstract_snapshot

        deployment.repo_version = ref.version if ref else deployment.repo_version + 1
        deployment.repo_hash = promoted_hash
        deployment.installed_hash = promoted_hash
        deployment.abstract_snapshot = promoted_snapshot
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=deployment.team_skill_id,
            user_id=deployment.user_id if auto else user_id,
            action="auto_promoted" if auto else "promoted",
            version=deployment.repo_version,
            diff_summary="auto hot update from deployment" if auto else "promoted from deployment",
            base_hash=deployment.repo_hash,
            new_hash=promoted_hash,
        )
        await session.commit()
        await session.refresh(deployment)
        return {"success": True, "deployment": _deployment_to_dict(deployment)}


async def refresh_deployment_dirty(deployment_id: str) -> None:
    """
    只读探测部署目录是否有未推送改动，仅更新 local_dirty / missing 标志。

    不写动态、不广播、不自动提升。真正的同步由用户手动 push 触发。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment or not deployment.tracking_enabled:
            return

        now = datetime.now(timezone.utc)
        current_hash = _compute_content_hash(deployment.install_path)

        if not current_hash:
            if deployment.status != "missing" or deployment.local_dirty:
                deployment.status = "missing"
                deployment.local_dirty = False
                deployment.last_seen_at = now
                await session.commit()
            return

        dirty = current_hash != deployment.installed_hash
        new_status = deployment.status
        if deployment.status == "missing":
            new_status = "changed" if dirty else "synced"

        if deployment.local_dirty != dirty or deployment.status != new_status:
            deployment.local_dirty = dirty
            deployment.status = new_status
            deployment.last_seen_at = now
            await session.commit()


async def get_deployment_local_status(
    deployment_id: str, user_id: str
) -> Dict[str, Any]:
    """只读检测本地部署目录是否有未推送改动，不写库、不进动态。"""
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot access another user's deployment"}

        install_path = deployment.install_path

    current_hash = _compute_content_hash(install_path)
    exists = Path(install_path).exists()
    has_local_changes = bool(current_hash) and current_hash != deployment.installed_hash
    return {
        "success": True,
        "exists": exists,
        "has_local_changes": has_local_changes,
        "installed_hash": deployment.installed_hash,
        "current_hash": current_hash,
        "status": deployment.status,
    }


async def _broadcast_push_event(
    *,
    project_id: str,
    skill_id: str,
    user_id: str,
    change_items: List[Dict[str, Any]],
    summary: str,
    status: str,
    event_type: str = "skill.pushed",
) -> None:
    """复用 SkillSyncService 的项目通道广播 skill 同步事件（带改动点）。"""
    from app.services.skill_sync_service import SkillSyncService

    user_display_name = await SkillSyncService._get_user_display_name(user_id)
    skill_display_name = await SkillSyncService._get_skill_display_name(skill_id)
    event = {
        "type": event_type,
        "project_id": project_id,
        "skill_id": skill_id,
        "version": 0,
        "content_hash": "",
        "user_id": user_id,
        "user_display_name": user_display_name,
        "skill_display_name": skill_display_name,
        "diff_summary": summary,
        "change_items": change_items,
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    await SkillSyncService._broadcast(project_id, event)


async def _mark_other_deployments_outdated(
    *,
    session,
    project_id: str,
    skill_id: str,
    exclude_deployment_id: str,
    repo_version: int,
    repo_hash: str,
) -> None:
    """
    某设备推送写回团队仓库后，把同项目同 Skill 的其他部署实例标记为落后。

    - 本地有未推送改动（local_dirty）→ conflict（拉取会覆盖本地改动，需确认）
    - 否则 → outdated（可直接拉取团队最新）
    其余设备/用户的 repo_version/repo_hash 更新为团队最新。
    """
    result = await session.execute(
        select(UserSkillDeployment).where(
            UserSkillDeployment.project_id == project_id,
            UserSkillDeployment.team_skill_id == skill_id,
            UserSkillDeployment.id != exclude_deployment_id,
            UserSkillDeployment.tracking_enabled.is_(True),
        )
    )
    for dep in result.scalars().all():
        if dep.status in ("untracked", "missing"):
            continue
        dep.repo_version = repo_version
        dep.repo_hash = repo_hash
        dep.status = "conflict" if dep.local_dirty else "outdated"


async def mark_skill_deployments_outdated(skill_id: str, editor_user_id: str) -> None:
    """团队（平台）仓库 Skill 被网页编辑器直接编辑保存后调用。

    把该 Skill 的所有部署实例（跨项目、跨用户，含编辑者本人的本地部署）标记为
    落后于团队仓库：本地有未推送改动则 conflict，否则 outdated；并把 repo_hash /
    repo_version 推进到团队仓库最新，使各成员可在项目页点「更新本地」一键拉取。

    版本递增 / 项目动态记录 / WebSocket 广播由 SkillSyncService.on_skill_changed 负责，
    本函数只负责推进部署实例的同步状态。
    """
    async with async_session_factory() as session:
        pkg = await session.get(TeamSkill, skill_id)
        latest_hash = (
            _compute_store_hash(pkg.store_path) if pkg and pkg.store_path else ""
        )

        refs = (
            await session.execute(
                select(ProjectSkill).where(ProjectSkill.skill_id == skill_id)
            )
        ).scalars().all()
        version_by_project = {ref.project_id: ref.version for ref in refs}

        deployments = (
            await session.execute(
                select(UserSkillDeployment).where(
                    UserSkillDeployment.team_skill_id == skill_id,
                    UserSkillDeployment.tracking_enabled.is_(True),
                )
            )
        ).scalars().all()

        for dep in deployments:
            if dep.status in ("untracked", "missing"):
                continue
            dep.repo_hash = latest_hash
            dep.repo_version = version_by_project.get(
                dep.project_id, dep.repo_version
            )
            dep.status = "conflict" if dep.local_dirty else "outdated"

        await session.commit()


async def push_deployment(
    deployment_id: str,
    user_id: str,
    create_version: bool = False,
    version_number: str = "",
    version_label: str = "",
) -> Dict[str, Any]:
    """
    用户手动推送本地部署实例改动：解析原生→抽象包，与上次推送快照对比，
    生成抽象层改动点；无冲突则写回团队仓库（推送即同步到平台），
    并把同 Skill 其他用户实例标记为可更新/冲突。

    create_version=True 时（用户在"是否更新版本号"弹窗选择"是"），推送成功后
    对团队仓库当前内容打一条版本快照（可在 Skill 详情页查看/回滚）。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot push another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}

        # 团队仓库已被他人推送到更新版本（outdated/conflict）→ 必须先更新本地再推送，
        # 否则会用陈旧内容覆盖团队最新版本。
        if deployment.status in ("outdated", "conflict"):
            return {
                "success": False,
                "conflict": True,
                "status": deployment.status,
                "error": "团队仓库已更新，请先更新本地再推送",
            }

        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        team = await session.get(Team, project.team_id) if project else None
        if not project or not pkg:
            return {"success": False, "error": "Project or skill not found"}

        install_path = deployment.install_path
        now = datetime.now(timezone.utc)
        current_hash = _compute_content_hash(install_path)

        if not current_hash:
            deployment.status = "missing"
            deployment.local_dirty = False
            deployment.last_seen_at = now
            await _write_change_log(
                session=session,
                team_id=project.team_id,
                project_id=project.id,
                deployment_id=deployment.id,
                skill_id=deployment.team_skill_id,
                user_id=user_id,
                action="missing",
                version=deployment.repo_version,
                diff_summary="部署路径缺失",
                base_hash=deployment.installed_hash,
                new_hash="",
            )
            await session.commit()
            return {
                "success": False,
                "error": "Deployment files missing",
                "status": "missing",
            }

        if current_hash == deployment.installed_hash:
            if deployment.local_dirty:
                deployment.local_dirty = False
                deployment.last_seen_at = now
                await session.commit()
            return {
                "success": True,
                "no_change": True,
                "change_items": [],
                "diff_summary": "无改动",
                "deployment": _deployment_to_dict(deployment),
            }

        try:
            current_pkg = parse_native_skill(install_path, deployment.tool_type)
        except Exception as e:
            return {"success": False, "error": f"解析本地 Skill 失败: {e}"}

        base_pkg = None
        if deployment.abstract_snapshot:
            try:
                base_pkg = json.loads(deployment.abstract_snapshot)
            except Exception:
                base_pkg = None

        change_items = diff_abstract_packages(base_pkg, current_pkg)
        summary = summarize_changes(change_items)

        team_hash = _compute_store_hash(pkg.store_path) if pkg.store_path else ""
        conflict = bool(deployment.repo_hash and deployment.repo_hash != team_hash)

        # 冲突：团队仓库在本次部署后被他人推送过，拦截本次推送
        if conflict:
            old_hash = deployment.installed_hash
            deployment.installed_hash = current_hash
            deployment.abstract_snapshot = json.dumps(current_pkg, ensure_ascii=False)
            deployment.status = "conflict"
            deployment.local_dirty = False
            deployment.last_seen_at = now
            await _write_change_log(
                session=session,
                team_id=project.team_id,
                project_id=project.id,
                deployment_id=deployment.id,
                skill_id=deployment.team_skill_id,
                user_id=user_id,
                action="conflict",
                version=deployment.repo_version,
                diff_summary="团队仓库已更新，推送被拦截",
                base_hash=old_hash,
                new_hash=current_hash,
                change_items=change_items,
            )
            await session.commit()
            await session.refresh(deployment)
            return {
                "success": False,
                "conflict": True,
                "status": "conflict",
                "error": "团队仓库已更新，请先更新本地再推送",
                "change_items": change_items,
                "diff_summary": summary,
                "deployment": _deployment_to_dict(deployment),
            }

        pre_push_hash = deployment.installed_hash
        skill_id = deployment.team_skill_id
        tool_type = deployment.tool_type
        project_team_id = project.team_id
        project_id_val = project.id

    resolved_version_number = ""
    if create_version:
        from app.services.skill_version_service import SkillVersionService

        try:
            resolved_version_number = await SkillVersionService.resolve_version_number(
                skill_id,
                version_number,
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    # 无冲突：解析后的本地内容写回团队仓库（推送即同步到平台）
    await NativeSkillStore.import_from_external(
        install_path,
        tool_type,
        allow_team_update=True,
        target_skill_id=skill_id,
    )

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )

        promoted_hash = _compute_store_hash(pkg.store_path) if pkg and pkg.store_path else ""
        if pkg:
            # 拆表后 pkg 即团队表行，team_id 已固定，无需再翻转 scope。
            pkg.content_hash = promoted_hash
        new_version = deployment.repo_version + 1
        if ref:
            ref.version += 1
            ref.content_hash = promoted_hash
            ref.last_modified_by = user_id
            new_version = ref.version

        try:
            promoted_snapshot = json.dumps(
                parse_native_skill(deployment.install_path, deployment.tool_type),
                ensure_ascii=False,
            )
        except Exception:
            promoted_snapshot = deployment.abstract_snapshot

        installed_hash_after = _compute_content_hash(deployment.install_path)

        deployment.repo_version = new_version
        deployment.repo_hash = promoted_hash
        deployment.installed_hash = installed_hash_after or current_hash
        deployment.abstract_snapshot = promoted_snapshot
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else project_team_id,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="pushed",
            version=new_version,
            diff_summary=summary,
            base_hash=pre_push_hash,
            new_hash=promoted_hash,
            change_items=change_items,
        )

        await _mark_other_deployments_outdated(
            session=session,
            project_id=deployment.project_id,
            skill_id=skill_id,
            exclude_deployment_id=deployment.id,
            repo_version=new_version,
            repo_hash=promoted_hash,
        )

        await session.commit()
        await session.refresh(deployment)
        result_deployment = _deployment_to_dict(deployment)

    await _broadcast_push_event(
        project_id=project_id_val,
        skill_id=skill_id,
        user_id=user_id,
        change_items=change_items,
        summary=summary,
        status="synced",
    )

    version = None
    if create_version:
        version = await _maybe_create_version(
            skill_id=skill_id,
            user_id=user_id,
            version_number=resolved_version_number,
            label=version_label,
            summary=summary,
            change_items=change_items,
        )

    return {
        "success": True,
        "no_change": False,
        "status": "synced",
        "conflict": False,
        "change_items": change_items,
        "diff_summary": summary,
        "deployment": result_deployment,
        "version": version,
    }


async def _maybe_create_version(
    *,
    skill_id: str,
    user_id: str,
    version_number: str,
    label: str,
    summary: str,
    change_items: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """推送成功后按需创建版本快照；失败不阻断推送主流程。"""
    try:
        from app.services.skill_version_service import SkillVersionService

        return await SkillVersionService.create_version(
            skill_id,
            created_by=user_id,
            source="push",
            version_number=version_number,
            label=label or "",
            change_summary=summary,
            change_items=change_items,
        )
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[push] 创建版本快照失败 skill='{skill_id}': {e}")
        return None


async def pull_update_deployment(
    deployment_id: str, user_id: str, overwrite: bool = False
) -> Dict[str, Any]:
    """
    把团队仓库最新内容拉取并写回当前用户的本地部署目录。

    本地有未推送改动时默认拦截（需 overwrite 才覆盖）。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot pull another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}

        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        if not project or not pkg or not ref:
            return {"success": False, "error": "Project skill relation missing"}

        skill_id = deployment.team_skill_id
        tool_type = deployment.tool_type
        deploy_path = deployment.deploy_path
        install_path = deployment.install_path
        prev_installed_hash = deployment.installed_hash

    current_local_hash = _compute_content_hash(install_path)
    has_local_changes = bool(current_local_hash) and current_local_hash != prev_installed_hash
    if has_local_changes and not overwrite:
        return {
            "success": False,
            "conflict": True,
            "error": "本地有未推送改动，更新将覆盖本地，请确认",
        }

    result = await NativeSkillStore.deploy(
        skill_id,
        tool_type,
        dest_path=deploy_path,
        notify=False,
        allow_team=True,
    )
    if not result.get("success"):
        return result

    installed_hash_after = _compute_content_hash(install_path)
    try:
        snapshot_json = json.dumps(
            parse_native_skill(install_path, tool_type), ensure_ascii=False
        )
    except Exception as e:
        logger.warning(f"[pull] 解析抽象包失败 skill='{skill_id}': {e}")
        snapshot_json = ""

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        team_hash = _compute_store_hash(pkg.store_path) if pkg and pkg.store_path else ""

        deployment.repo_version = ref.version if ref else deployment.repo_version
        deployment.repo_hash = team_hash
        deployment.installed_hash = installed_hash_after or team_hash
        deployment.abstract_snapshot = snapshot_json
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="pulled",
            version=deployment.repo_version,
            diff_summary="更新本地到团队最新",
            base_hash=prev_installed_hash,
            new_hash=team_hash,
            source="team_repo",
        )
        await session.commit()
        await session.refresh(deployment)
        result_deployment = _deployment_to_dict(deployment)
        broadcast_project_id = deployment.project_id

    await _broadcast_push_event(
        project_id=broadcast_project_id,
        skill_id=skill_id,
        user_id=user_id,
        change_items=[],
        summary="更新本地到团队最新",
        status="synced",
        event_type="skill.pulled",
    )

    return {
        "success": True,
        "conflict": False,
        "deployment": result_deployment,
    }


async def list_user_deployments(user_id: str) -> List[Dict[str, Any]]:
    """列出当前用户跨项目的全部部署实例，供无头客户端寻址。

    只按部署行自身的 user_id 隔离，不依赖客户端提供 project/team 条件，避免
    CLI 为枚举 deployment_id 逐项目请求。排序固定为最近更新优先，便于 status
    输出稳定且优先展示活跃部署。
    """
    async with async_session_factory() as session:
        device_id = await _active_device_id(session, user_id)
        if not device_id:
            return []
        result = await session.execute(
            select(UserSkillDeployment)
            .join(Project, Project.id == UserSkillDeployment.project_id)
            .join(
                TeamMember,
                (TeamMember.team_id == Project.team_id)
                & (TeamMember.user_id == user_id),
            )
            .where(
                UserSkillDeployment.user_id == user_id,
                UserSkillDeployment.device_id == device_id,
            )
            .order_by(
                UserSkillDeployment.updated_at.desc(),
                UserSkillDeployment.id,
            )
        )
        return [_deployment_to_dict(row) for row in result.scalars().all()]


async def list_tracked_deployments() -> List[Dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(UserSkillDeployment).where(
                UserSkillDeployment.tracking_enabled.is_(True)
            )
        )
        return [_deployment_to_dict(row) for row in result.scalars().all()]


# ==================================================================
# 方案 B · M4 云端编排端点（薄代理：云端不读/写用户本地磁盘）
#
# 灰度并存：以上「一次性」端点（deploy_project_skill / push_deployment /
# pull_update_deployment）原样保留，维持 local 形态。以下编排端点供 cloud/桌面
# 形态使用，由前端串联「云端产物 → 本地代理落盘 → 本地代理算 hash → 云端登记」。
# hash 一致性：云端涉及的 hash 仍用 _compute_content_hash（M1 收敛算法，与 M3
# 本地代理位级一致）；install 目录 hash 一律由前端经本地代理上报，云端不读本地盘。
# ==================================================================


def _assemble_artifact(
    skill_id: str,
    tool: str,
    repo_version: int,
    store_path: str,
    build_outputs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """纯函数：把构建输出 + Store 资源组装为构建产物（不触 DB、不调 Node）。

    - contents 取与 tool 匹配的构建输出文本；
    - resources 从 Store 归集（含二进制，base64 inline）；
    - abstract_snapshot 在临时目录重建「contents + 资源」后 parse_native_skill 直接
      生成（M0 §3.1 / 分歧 D4 选项 A），临时目录用完即删；
    - repo_hash = _compute_store_hash(store_path)（M1 收敛算法，与本地代理位级一致）。
    """
    contents: Dict[str, str] = {}
    for out in build_outputs or []:
        if out.get("target") == tool:
            contents = out.get("contents", {}) or {}
            break
    else:
        if build_outputs:
            contents = build_outputs[0].get("contents", {}) or {}

    resources = collect_store_resources(store_path)

    abstract_snapshot: Dict[str, Any] = {}
    try:
        with tempfile.TemporaryDirectory() as td:
            install_dir = Path(td) / "install"
            build_install_tree(install_dir, contents, resources)
            abstract_snapshot = parse_native_skill(str(install_dir), tool)
    except Exception as e:
        logger.warning(f"[build-artifact] 生成抽象快照失败 skill='{skill_id}': {e}")
        abstract_snapshot = {}

    return {
        "success": True,
        "skill_id": skill_id,
        "tool": tool,
        "contents": contents,
        "resources": resources,
        "repo_hash": _compute_store_hash(store_path),
        "repo_version": repo_version,
        "abstract_snapshot": abstract_snapshot,
    }


async def _build_artifact_payload(
    skill_id: str, tool: str, repo_version: int
) -> Dict[str, Any]:
    """云端构建产物：contents(文本) + resources(Store 资源) + repo_hash + 抽象快照。

    构建留云端（call_bridge），**不写后端磁盘**；产物组装见 _assemble_artifact。
    """
    tool = (tool or "").lower()
    if tool not in SUPPORTED_TOOLS:
        return {"success": False, "error": "tool must be cursor, codex, windsurf, claude, kiro, trae, qoder or workbuddy"}

    # API 使用内部记录 id 寻址；构建产物返回自然名供本地代理作为安装目录名。
    async with async_session_factory() as session:
        pkg = await session.get(TeamSkill, skill_id)
        if pkg is None:
            pkg = await session.get(PersonalSkill, skill_id)
        store_path = pkg.store_path if pkg else ""
        install_name = pkg.name if pkg else ""
    if not store_path:
        logger.warning(
            "[build-artifact] 未找到 Skill 内容 skill_id=%s backend=%s "
            "（对象存储与 DB 均无 store_path）",
            skill_id,
            settings.STORAGE_BACKEND,
        )
        return {"success": False, "error": f"Skill '{skill_id}' not found"}

    try:
        build_result = await NativeSkillStore.build(skill_id, tool)
    except FileNotFoundError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.exception(f"[build-artifact] 构建失败 skill='{skill_id}'")
        return {"success": False, "error": f"build failed: {e}"}

    return _assemble_artifact(
        install_name, tool, repo_version, store_path, build_result.get("data", []) or []
    )


async def build_project_skill_artifact(
    project_id: str, skill_id: str, user_id: str, tool: str
) -> Dict[str, Any]:
    """① 构建产物端点（deploy 用）：POST /projects/{pid}/skills/{sid}/build-artifact。

    项目访问权由 API 层 _check_project_access 校验；此处校验 Skill 已关联项目。
    """
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        pkg = await session.get(TeamSkill, skill_id)
        if not project or not pkg:
            return {"success": False, "error": "Project or skill not found"}
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        if not ref:
            return {"success": False, "error": "Skill is not added to this project"}
        repo_version = ref.version

    return await _build_artifact_payload(skill_id, tool, repo_version)


async def build_store_skill_artifact(
    skill_id: str, user_id: str, tool: str
) -> Dict[str, Any]:
    """① 构建产物端点（store 级，个人/团队仓库部署用）。

    对应前端 deployNativeSkillOrchestrated → POST /skill-forge/store/{sid}/build-artifact。
    契约 §9 未单列 store 级 build-artifact，本端点补齐并与前端调用对齐：返回
    contents+resources+repoHash+abstractSnapshot，**不写后端盘**。归属由调用方
    （skill_store API 的 _assert_skill_accessible）校验。

    repo_version 对个人/团队仓库 Skill 无项目版本语义，固定 0（前端该路径不登记
    deployment，repoVersion 不被消费）。
    """
    return await _build_artifact_payload(skill_id, tool, 0)


async def build_deployment_artifact(
    deployment_id: str, user_id: str
) -> Dict[str, Any]:
    """① 构建产物端点（pull 用）：POST /skill-deployments/{id}/build-artifact。

    返回团队仓库最新构建产物供前端覆盖落盘；归属由部署实例 user_id 校验。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot access another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}
        skill_id = deployment.team_skill_id
        tool = deployment.tool_type
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        repo_version = ref.version if ref else deployment.repo_version

    return await _build_artifact_payload(skill_id, tool, repo_version)


async def register_deployment(
    project_id: str,
    skill_id: str,
    user_id: str,
    tool: str,
    deploy_path: str,
    install_path: str,
    installed_hash: str,
    repo_hash: str = "",
    repo_version: int = 1,
    abstract_snapshot: Optional[Dict[str, Any]] = None,
    overwrite: bool = False,
) -> Dict[str, Any]:
    """④ 登记部署元数据 + change log（对应 deploy_project_skill 的写库段）。

    installed_hash 为本地代理对 installPath 实算（权威）；repo_hash/repo_version/
    abstract_snapshot 来自先前 build-artifact，前端透传。**云端不读本地盘**。
    """
    tool = (tool or "").lower()
    if tool not in SUPPORTED_TOOLS:
        return {"success": False, "error": "tool must be cursor, codex, windsurf, claude, kiro, trae, qoder or workbuddy"}
    if not deploy_path:
        return {"success": False, "error": "deploy_path is required"}
    if not install_path:
        return {"success": False, "error": "install_path is required"}

    snapshot_json = (
        json.dumps(abstract_snapshot, ensure_ascii=False) if abstract_snapshot else ""
    )
    deploy_path_norm = str(Path(deploy_path))
    now = datetime.now(timezone.utc)

    async with async_session_factory() as session:
        await session.scalar(
            select(User).where(User.id == user_id).with_for_update()
        )
        device_id = await _active_device_id(session, user_id)
        if not device_id:
            return {"success": False, "error": "当前登录未绑定有效设备，请重新登录"}
        project = await session.get(Project, project_id)
        pkg = await session.get(TeamSkill, skill_id)
        if not project or not pkg:
            return {"success": False, "error": "Project or skill not found"}
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        if not ref:
            return {"success": False, "error": "Skill is not added to this project"}

        existing = await session.scalar(
            select(UserSkillDeployment).where(
                UserSkillDeployment.user_id == user_id,
                UserSkillDeployment.device_id == device_id,
                UserSkillDeployment.project_id == project_id,
                UserSkillDeployment.team_skill_id == skill_id,
                UserSkillDeployment.tool_type == tool,
                UserSkillDeployment.deploy_path == deploy_path_norm,
            )
        )
        deployment = existing or UserSkillDeployment(
            user_id=user_id,
            device_id=device_id,
            project_id=project_id,
            team_skill_id=skill_id,
            tool_type=tool,
            deploy_path=deploy_path_norm,
        )
        deployment.skill_name = skill_id
        deployment.install_path = install_path
        deployment.repo_version = repo_version or (ref.version if ref else 1)
        deployment.repo_hash = repo_hash or (ref.content_hash if ref else "")
        deployment.installed_hash = installed_hash
        deployment.abstract_snapshot = snapshot_json
        deployment.status = "synced"
        deployment.tracking_enabled = True
        deployment.local_dirty = False
        deployment.last_seen_at = now
        session.add(deployment)
        await session.flush()

        await _write_change_log(
            session=session,
            team_id=project.team_id,
            project_id=project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="deployed",
            version=deployment.repo_version,
            diff_summary=f"deployed to {tool}: {deployment.install_path}",
            base_hash=deployment.repo_hash,
            new_hash=installed_hash,
        )
        await session.commit()
        await session.refresh(deployment)
        return {"success": True, "deployment": _deployment_to_dict(deployment)}


async def commit_pull(
    deployment_id: str,
    user_id: str,
    installed_hash: str,
    repo_hash: str = "",
    repo_version: int = 1,
    abstract_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """拉取提交（对应 pull_update_deployment 的写库段）：覆盖落盘后登记同步状态。

    installed_hash 为覆盖写后本地代理实算（权威）；其余字段来自团队最新 build-artifact。
    写 change_log(action=pulled, source=team_repo) 并广播 skill.pulled。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot pull another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}

        project = await session.get(Project, deployment.project_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        skill_id = deployment.team_skill_id
        prev_installed_hash = deployment.installed_hash

        snapshot_json = (
            json.dumps(abstract_snapshot, ensure_ascii=False)
            if abstract_snapshot
            else deployment.abstract_snapshot
        )
        new_repo_hash = repo_hash or deployment.repo_hash
        new_repo_version = repo_version or (ref.version if ref else deployment.repo_version)

        deployment.repo_version = new_repo_version
        deployment.repo_hash = new_repo_hash
        deployment.installed_hash = installed_hash or deployment.installed_hash
        deployment.abstract_snapshot = snapshot_json
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="pulled",
            version=deployment.repo_version,
            diff_summary="更新本地到团队最新",
            base_hash=prev_installed_hash,
            new_hash=new_repo_hash,
            source="team_repo",
        )
        await session.commit()
        await session.refresh(deployment)
        result_deployment = _deployment_to_dict(deployment)
        broadcast_project_id = deployment.project_id

    await _broadcast_push_event(
        project_id=broadcast_project_id,
        skill_id=skill_id,
        user_id=user_id,
        change_items=[],
        summary="更新本地到团队最新",
        status="synced",
        event_type="skill.pulled",
    )

    return {"success": True, "conflict": False, "deployment": result_deployment}


async def push_deployment_content(
    deployment_id: str,
    user_id: str,
    current_hash: str,
    files: List[Dict[str, Any]],
    expected_repo_hash: str = "",
    create_version: bool = False,
    version_number: str = "",
    version_label: str = "",
) -> Dict[str, Any]:
    """按 Skill 串行写团队仓库，并用客户端基线 hash 做乐观锁校验。"""
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        skill_id = deployment.team_skill_id
    async with _skill_write_lock(skill_id):
        return await _push_deployment_content_unlocked(
            deployment_id,
            user_id,
            current_hash,
            files,
            expected_repo_hash=expected_repo_hash,
            create_version=create_version,
            version_number=version_number,
            version_label=version_label,
        )


async def _push_deployment_content_unlocked(
    deployment_id: str,
    user_id: str,
    current_hash: str,
    files: List[Dict[str, Any]],
    expected_repo_hash: str = "",
    create_version: bool = False,
    version_number: str = "",
    version_label: str = "",
) -> Dict[str, Any]:
    """③ 推送（接收上传内容）：对应 push_deployment，但输入改为上传的 install 内容。

    前端经本地代理 read-folder 把 install 目录全量文件上传，云端在临时目录重建后
    复用既有 push 语义（解析→抽象包 diff→冲突判定→写回 Store→版本提升→标记其他
    实例 outdated/conflict→广播）。**云端不读用户本地盘**；team_hash 仍取云端 Store。
    """
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot push another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}

        # 团队仓库已被他人推送到更新版本（outdated/conflict）→ 必须先更新本地再推送。
        if deployment.status in ("outdated", "conflict"):
            return {
                "success": False,
                "conflict": True,
                "status": deployment.status,
                "error": "团队仓库已更新，请先更新本地再推送",
            }

        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, deployment.team_skill_id)
        if not project or not pkg:
            return {"success": False, "error": "Project or skill not found"}

        now = datetime.now(timezone.utc)
        skill_id = deployment.team_skill_id
        tool_type = deployment.tool_type
        base_snapshot = deployment.abstract_snapshot
        repo_hash_at_deploy = deployment.repo_hash
        installed_hash_before = deployment.installed_hash
        store_path = pkg.store_path
        project_team_id = project.team_id
        project_id_val = project.id

        # install 目录缺失（前端经 local hash 得知 exists=false → 上报空 hash / 空 files）
        if not current_hash or not files:
            deployment.status = "missing"
            deployment.local_dirty = False
            deployment.last_seen_at = now
            await _write_change_log(
                session=session,
                team_id=project_team_id,
                project_id=project_id_val,
                deployment_id=deployment.id,
                skill_id=skill_id,
                user_id=user_id,
                action="missing",
                version=deployment.repo_version,
                diff_summary="部署路径缺失",
                base_hash=installed_hash_before,
                new_hash="",
            )
            await session.commit()
            return {"success": False, "error": "Deployment files missing", "status": "missing"}

        # 无改动（本地实时 hash == 上次部署/推送记录的 installed_hash）
        if current_hash == installed_hash_before:
            if deployment.local_dirty:
                deployment.local_dirty = False
                deployment.last_seen_at = now
                await session.commit()
            return {
                "success": True,
                "no_change": True,
                "change_items": [],
                "diff_summary": "无改动",
                "deployment": _deployment_to_dict(deployment),
            }

    # 临时目录重建上传内容 → 解析抽象包 → diff
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "upload"
        try:
            write_files(src, files)
        except ValueError as e:
            return {"success": False, "error": f"上传内容非法: {e}"}

        try:
            current_pkg = parse_native_skill(str(src), tool_type)
        except Exception as e:
            return {"success": False, "error": f"解析上传 Skill 失败: {e}"}

        base_pkg = None
        if base_snapshot:
            try:
                base_pkg = json.loads(base_snapshot)
            except Exception:
                base_pkg = None

        change_items = diff_abstract_packages(base_pkg, current_pkg)
        summary = summarize_changes(change_items)

        team_hash = _compute_store_hash(store_path) if store_path else ""
        expected_hash = expected_repo_hash or repo_hash_at_deploy
        conflict = bool(expected_hash and expected_hash != team_hash)

        # 冲突：团队仓库在本次部署后被他人推送过，拦截本次推送
        if conflict:
            async with async_session_factory() as session:
                deployment = await session.get(UserSkillDeployment, deployment_id)
                project = await session.get(Project, deployment.project_id)
                old_hash = deployment.installed_hash
                deployment.installed_hash = current_hash
                deployment.abstract_snapshot = json.dumps(current_pkg, ensure_ascii=False)
                deployment.status = "conflict"
                deployment.local_dirty = False
                deployment.last_seen_at = datetime.now(timezone.utc)
                await _write_change_log(
                    session=session,
                    team_id=project.team_id if project else project_team_id,
                    project_id=deployment.project_id,
                    deployment_id=deployment.id,
                    skill_id=skill_id,
                    user_id=user_id,
                    action="conflict",
                    version=deployment.repo_version,
                    diff_summary="团队仓库已更新，推送被拦截",
                    base_hash=old_hash,
                    new_hash=current_hash,
                    change_items=change_items,
                )
                await session.commit()
                await session.refresh(deployment)
                conflict_deployment = _deployment_to_dict(deployment)
            return {
                "success": False,
                "conflict": True,
                "status": "conflict",
                "error": "团队仓库已更新，请先更新本地再推送",
                "change_items": change_items,
                "diff_summary": summary,
                "deployment": conflict_deployment,
            }

        resolved_version_number = ""
        if create_version:
            from app.services.skill_version_service import SkillVersionService

            try:
                resolved_version_number = (
                    await SkillVersionService.resolve_version_number(
                        skill_id,
                        version_number,
                    )
                )
            except ValueError as exc:
                return {"success": False, "error": str(exc)}

        # 无冲突：解析后的上传内容写回团队仓库（推送即同步到平台）
        await NativeSkillStore.import_from_external(
            str(src),
            tool_type,
            allow_team_update=True,
            target_skill_id=skill_id,
        )

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        project = await session.get(Project, deployment.project_id)
        pkg = await session.get(TeamSkill, skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )

        promoted_hash = _compute_store_hash(pkg.store_path) if pkg and pkg.store_path else ""
        if pkg:
            # 拆表后 pkg 即团队表行，team_id 已固定，无需再翻转 scope。
            pkg.content_hash = promoted_hash
        new_version = deployment.repo_version + 1
        if ref:
            ref.version += 1
            ref.content_hash = promoted_hash
            ref.last_modified_by = user_id
            new_version = ref.version

        # 推送内容的抽象包即上传内容解析结果（current_pkg），无需再读本地盘
        promoted_snapshot = json.dumps(current_pkg, ensure_ascii=False)

        deployment.repo_version = new_version
        deployment.repo_hash = promoted_hash
        # push 不重写本地（本地已是最新），新 installed_hash 直接用 currentHash（M0 §3.2）
        deployment.installed_hash = current_hash
        deployment.abstract_snapshot = promoted_snapshot
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else project_team_id,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="pushed",
            version=new_version,
            diff_summary=summary,
            base_hash=installed_hash_before,
            new_hash=promoted_hash,
            change_items=change_items,
        )

        await _mark_other_deployments_outdated(
            session=session,
            project_id=deployment.project_id,
            skill_id=skill_id,
            exclude_deployment_id=deployment.id,
            repo_version=new_version,
            repo_hash=promoted_hash,
        )

        await session.commit()
        await session.refresh(deployment)
        result_deployment = _deployment_to_dict(deployment)

    await _broadcast_push_event(
        project_id=project_id_val,
        skill_id=skill_id,
        user_id=user_id,
        change_items=change_items,
        summary=summary,
        status="synced",
    )

    version = None
    if create_version:
        version = await _maybe_create_version(
            skill_id=skill_id,
            user_id=user_id,
            version_number=resolved_version_number,
            label=version_label,
            summary=summary,
            change_items=change_items,
        )

    return {
        "success": True,
        "no_change": False,
        "status": "synced",
        "conflict": False,
        "change_items": change_items,
        "diff_summary": summary,
        "deployment": result_deployment,
        "version": version,
    }


# ------------------------------------------------------------------
# AI 辅助合并（冲突一键合并），设计见 docs/design/ai-assisted-merge.md
# ------------------------------------------------------------------

_RESOURCE_DIRS = ("scripts/", "references/", "assets/")


def _deep_merge_dict(base: Dict[str, Any], overlay: Dict[str, Any]) -> Dict[str, Any]:
    """把 overlay 深合并进 base 的副本（dict 递归，其余覆盖）。"""
    import copy

    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for k, v in (overlay or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def _mine_resource_contents(files: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """从上传 files[] 抽出 scripts/references/assets 资源 → {path: {encoding, content}}。"""
    out: Dict[str, Dict[str, Any]] = {}
    for f in files or []:
        path = str(f.get("path", "")).replace("\\", "/").lstrip("/")
        if path.startswith(_RESOURCE_DIRS):
            out[path] = {
                "encoding": f.get("encoding", "utf8") or "utf8",
                "content": f.get("content", ""),
            }
    return out


def _apply_merged_config_to_native(src: Path, config: Dict[str, Any], body: str) -> None:
    """把合并后的正文与白名单配置字段写回 mine 的 native 临时树。

    - 正文 + name/description/metadata 写回 SKILL.md frontmatter；
    - ui/policy/dependencies 写回 agents/openai.yaml（import_from_external 据此回收为
      抽象 config，无关 tool 类型；origin 显式传入故不会误判平台）。
    """
    import yaml

    from app.services.native_skill_store import _parse_skill_md, _read_yaml

    skill_md = src / "SKILL.md"
    frontmatter: Dict[str, Any] = {}
    if skill_md.exists():
        frontmatter, _old_body = _parse_skill_md(skill_md)
    if not isinstance(frontmatter, dict):
        frontmatter = {}

    if "description" in config:
        frontmatter["description"] = config.get("description")

    md = config.get("metadata") if isinstance(config.get("metadata"), dict) else {}
    if md.get("license") is not None:
        frontmatter["license"] = md["license"]
    if md.get("author") is not None or md.get("version") is not None:
        fm_meta = frontmatter.get("metadata")
        fm_meta = fm_meta if isinstance(fm_meta, dict) else {}
        if md.get("author") is not None:
            fm_meta["author"] = md["author"]
        if md.get("version") is not None:
            fm_meta["version"] = md["version"]
        frontmatter["metadata"] = fm_meta

    fm_text = (
        yaml.dump(frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False)
        if frontmatter
        else ""
    )
    skill_md.write_bytes(f"---\n{fm_text}---\n{body}".encode("utf-8"))

    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    pol = config.get("policy") if isinstance(config.get("policy"), dict) else {}
    deps = config.get("dependencies") if isinstance(config.get("dependencies"), dict) else {}
    auto_invoke = pol.get("auto_invoke")
    if ui or auto_invoke is not None or deps.get("tools"):
        agents_dir = src / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True)
        oa_path = agents_dir / "openai.yaml"
        oa = _read_yaml(oa_path) if oa_path.exists() else {}
        if not isinstance(oa, dict):
            oa = {}
        interface = oa.get("interface") if isinstance(oa.get("interface"), dict) else {}
        for k, v in (ui or {}).items():
            if v is not None:
                interface[k] = v
        if interface:
            oa["interface"] = interface
        if auto_invoke is not None:
            policy = oa.get("policy") if isinstance(oa.get("policy"), dict) else {}
            policy["allow_implicit_invocation"] = auto_invoke
            oa["policy"] = policy
        if deps.get("tools"):
            d = oa.get("dependencies") if isinstance(oa.get("dependencies"), dict) else {}
            d["tools"] = deps["tools"]
            oa["dependencies"] = d
        oa_path.write_bytes(
            yaml.dump(oa, allow_unicode=True, sort_keys=False).encode("utf-8")
        )


def _apply_resource_ops_to_tree(
    src: Path,
    resource_ops: List[Dict[str, Any]],
    theirs_res_map: Dict[str, Dict[str, Any]],
) -> None:
    """以 mine 临时树为基底应用资源处置：use_mine 保留 / use_theirs 取团队内容 /
    write_text 写合并文本 / delete 删除。"""
    from app.services.content_transfer import _safe_join

    for op in resource_ops or []:
        path = str(op.get("path", "")).replace("\\", "/").lstrip("/")
        action = op.get("action", "use_mine")
        if not path:
            continue
        if action == "use_mine":
            continue
        if action == "delete":
            try:
                target = _safe_join(src, path)
            except ValueError:
                continue
            if target.exists():
                target.unlink()
            continue
        if action == "write_text":
            write_files(src, [{"path": path, "encoding": "utf8", "content": op.get("content", "")}])
            continue
        if action == "use_theirs":
            r = theirs_res_map.get(path)
            if not r:
                continue
            write_files(
                src,
                [{
                    "path": path,
                    "encoding": r.get("encoding", "utf8") or "utf8",
                    "content": r.get("content", ""),
                }],
            )


async def _load_theirs_for_merge(
    skill_id: str, tool_type: str, repo_version: int
) -> Optional[Dict[str, Any]]:
    """构建 theirs（团队仓库最新）：抽象包 + 资源内容 + repo_hash。失败返回 None。"""
    artifact = await _build_artifact_payload(skill_id, tool_type, repo_version)
    if not artifact.get("success"):
        return None
    theirs_pkg = artifact.get("abstract_snapshot") or {}
    res_list = artifact.get("resources") or []
    theirs_res_contents = {
        r.get("path"): {"encoding": r.get("encoding", "utf8"), "content": r.get("content", "")}
        for r in res_list
        if r.get("path")
    }
    return {
        "pkg": theirs_pkg,
        "res_contents": theirs_res_contents,
        "repo_hash": artifact.get("repo_hash", ""),
    }


async def merge_preview(
    deployment_id: str,
    user_id: str,
    current_hash: str,
    files: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """AI 合并预览：只算不写。返回合并稿（可编辑）+ 相对团队最新的预览 diff。"""
    import hashlib

    from app.services.skill_merge_service import merge_three_way

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot merge another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}
        skill_id = deployment.team_skill_id
        tool_type = deployment.tool_type
        base_snapshot = deployment.abstract_snapshot
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        repo_version = ref.version if ref else deployment.repo_version

    if not files:
        return {"success": False, "error": "本地内容缺失，无法合并"}

    base_pkg = None
    if base_snapshot:
        try:
            base_pkg = json.loads(base_snapshot)
        except Exception:
            base_pkg = None

    theirs = await _load_theirs_for_merge(skill_id, tool_type, repo_version)
    if theirs is None:
        return {"success": False, "error": "团队仓库内容构建失败，无法合并"}

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "mine"
        try:
            write_files(src, files)
            mine_pkg = parse_native_skill(str(src), tool_type)
        except Exception as e:
            return {"success": False, "error": f"解析本地 Skill 失败: {e}"}

    mine_res_contents = _mine_resource_contents(files)

    merged = await merge_three_way(
        base_pkg,
        mine_pkg,
        theirs["pkg"],
        mine_res_contents,
        theirs["res_contents"],
    )

    # 预览 diff：合并稿相对团队最新（theirs）的改动点
    theirs_cfg = (theirs["pkg"] or {}).get("config", {}) or {}
    merged_cfg = _deep_merge_dict(theirs_cfg, merged.get("config", {}))
    theirs_res = (theirs["pkg"] or {}).get("resources", {}) or {}
    mine_res = mine_pkg.get("resources", {}) or {}
    merged_res = dict(theirs_res)
    for op in merged.get("resource_ops", []):
        p = op.get("path")
        a = op.get("action")
        if not p:
            continue
        if a == "delete":
            merged_res.pop(p, None)
        elif a == "use_mine":
            if mine_res.get(p) is not None:
                merged_res[p] = mine_res[p]
            else:
                merged_res.pop(p, None)
        elif a == "use_theirs":
            if theirs_res.get(p) is not None:
                merged_res[p] = theirs_res[p]
        elif a == "write_text":
            merged_res[p] = hashlib.sha256((op.get("content", "") or "").encode("utf-8")).hexdigest()
    merged_pkg = {
        "config": merged_cfg,
        "vibeh_body": merged.get("body", ""),
        "resources": merged_res,
    }
    preview_change_items = diff_abstract_packages(theirs["pkg"], merged_pkg)

    return {
        "success": True,
        "merged": {
            "body": merged.get("body", ""),
            "config": merged.get("config", {}),
            "resource_ops": merged.get("resource_ops", []),
        },
        "preview_change_items": preview_change_items,
        "manual_conflicts": merged.get("manual_conflicts", []),
        "notes": merged.get("notes", []),
        "merge_available": merged.get("merge_available", False),
        "theirs_hash": theirs["repo_hash"],
    }


async def merge_apply(
    deployment_id: str,
    user_id: str,
    files: List[Dict[str, Any]],
    merged: Dict[str, Any],
    expected_theirs_hash: str = "",
) -> Dict[str, Any]:
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        skill_id = deployment.team_skill_id
    async with _skill_write_lock(skill_id):
        return await _merge_apply_unlocked(
            deployment_id,
            user_id,
            files,
            merged,
            expected_theirs_hash=expected_theirs_hash,
        )


async def _merge_apply_unlocked(
    deployment_id: str,
    user_id: str,
    files: List[Dict[str, Any]],
    merged: Dict[str, Any],
    expected_theirs_hash: str = "",
) -> Dict[str, Any]:
    """AI 合并提交（写回团队仓库）：乐观锁校验 → 补丁 mine 树 → import 写回 →
    version+1 → 返回 native 构建产物供前端覆盖落盘。"""
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot merge another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}
        skill_id = deployment.team_skill_id
        tool_type = deployment.tool_type

    if not files:
        return {"success": False, "error": "本地内容缺失，无法合并"}

    prefix, _scope = await NativeSkillStore._resolve_prefix(skill_id)
    if not prefix:
        return {"success": False, "error": "团队仓库内容缺失，无法合并"}

    # 乐观锁：预览之后团队仓库若被第三人再次推送，拦截并要求重新合并
    current_theirs_hash = _compute_store_hash(prefix)
    if expected_theirs_hash and current_theirs_hash != expected_theirs_hash:
        return {
            "success": False,
            "conflict": True,
            "error": "团队仓库已再次更新，请重新合并",
        }

    theirs_res_map = {
        r.get("path"): r for r in collect_store_resources(prefix) if r.get("path")
    }

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "merged"
        try:
            write_files(src, files)
            _apply_merged_config_to_native(src, merged.get("config", {}), merged.get("body", ""))
            _apply_resource_ops_to_tree(src, merged.get("resource_ops", []), theirs_res_map)
        except Exception as e:
            return {"success": False, "error": f"合并落盘失败: {e}"}

        try:
            await NativeSkillStore.import_from_external(
                str(src),
                tool_type,
                allow_team_update=True,
                target_skill_id=skill_id,
            )
        except Exception as e:
            return {"success": False, "error": f"写回团队仓库失败: {e}"}

    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        pkg = await session.get(TeamSkill, skill_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == skill_id,
            )
        )
        promoted_hash = _compute_store_hash(prefix)
        if pkg:
            pkg.content_hash = promoted_hash
        new_version = deployment.repo_version + 1
        if ref:
            ref.version += 1
            ref.content_hash = promoted_hash
            ref.last_modified_by = user_id
            new_version = ref.version
        await session.commit()

    artifact = await _build_artifact_payload(skill_id, tool_type, new_version)
    if not artifact.get("success"):
        return {"success": False, "error": artifact.get("error") or "构建合并产物失败"}

    return {"success": True, "conflict": False, "artifact": artifact}


async def commit_merge(
    deployment_id: str,
    user_id: str,
    installed_hash: str,
    repo_hash: str = "",
    repo_version: int = 1,
    abstract_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """AI 合并提交的登记段（对应 merge_apply 写回 + 本地覆盖落盘之后）：置 synced、
    写动态(action=merged)、标记其他成员 outdated、广播。"""
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if not deployment:
            return {"success": False, "error": "Deployment not found"}
        if deployment.user_id != user_id:
            return {"success": False, "error": "Cannot merge another user's deployment"}
        if not deployment.tracking_enabled:
            return {"success": False, "error": "Deployment tracking is disabled"}

        project = await session.get(Project, deployment.project_id)
        ref = await session.scalar(
            select(ProjectSkill).where(
                ProjectSkill.project_id == deployment.project_id,
                ProjectSkill.skill_id == deployment.team_skill_id,
            )
        )
        skill_id = deployment.team_skill_id
        prev_installed_hash = deployment.installed_hash

        snapshot_json = (
            json.dumps(abstract_snapshot, ensure_ascii=False)
            if abstract_snapshot
            else deployment.abstract_snapshot
        )
        new_repo_hash = repo_hash or deployment.repo_hash
        new_repo_version = repo_version or (ref.version if ref else deployment.repo_version)

        deployment.repo_version = new_repo_version
        deployment.repo_hash = new_repo_hash
        deployment.installed_hash = installed_hash or deployment.installed_hash
        deployment.abstract_snapshot = snapshot_json
        deployment.status = "synced"
        deployment.local_dirty = False
        deployment.last_seen_at = datetime.now(timezone.utc)

        await _write_change_log(
            session=session,
            team_id=project.team_id if project else None,
            project_id=deployment.project_id,
            deployment_id=deployment.id,
            skill_id=skill_id,
            user_id=user_id,
            action="merged",
            version=deployment.repo_version,
            diff_summary="AI 合并并提交",
            base_hash=prev_installed_hash,
            new_hash=new_repo_hash,
            source="user_deployment",
        )

        await _mark_other_deployments_outdated(
            session=session,
            project_id=deployment.project_id,
            skill_id=skill_id,
            exclude_deployment_id=deployment.id,
            repo_version=deployment.repo_version,
            repo_hash=new_repo_hash,
        )

        await session.commit()
        await session.refresh(deployment)
        result_deployment = _deployment_to_dict(deployment)
        broadcast_project_id = deployment.project_id

    await _broadcast_push_event(
        project_id=broadcast_project_id,
        skill_id=skill_id,
        user_id=user_id,
        change_items=[],
        summary="AI 合并并提交",
        status="synced",
    )

    return {"success": True, "conflict": False, "deployment": result_deployment}


# ------------------------------------------------------------------
# Sync metadata
# ------------------------------------------------------------------


async def get_sync_status(project_id: str) -> List[Dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(ProjectSkill).where(ProjectSkill.project_id == project_id)
        )
        return [
            {
                "skill_id": ps.skill_id,
                "version": ps.version,
                "content_hash": ps.content_hash,
                "updated_at": ps.updated_at.isoformat() if ps.updated_at else None,
            }
            for ps in result.scalars().all()
        ]


async def get_changes_since(
    project_id: str, since_version: int = 0
) -> List[Dict[str, Any]]:
    async with async_session_factory() as session:
        result = await session.execute(
            select(SkillChangeLog)
            .where(
                SkillChangeLog.project_id == project_id,
                SkillChangeLog.version > since_version,
            )
            .order_by(SkillChangeLog.created_at.desc())
            .limit(50)
        )
        rows = result.scalars().all()

        user_ids = list({log.user_id for log in rows if log.user_id})
        skill_ids = list({log.skill_id for log in rows})

        user_map: Dict[str, str] = {"system": "System"}
        if user_ids:
            users_result = await session.execute(select(User).where(User.id.in_(user_ids)))
            for user in users_result.scalars().all():
                user_map[user.id] = user.display_name or user.username

        skill_map: Dict[str, str] = {}
        if skill_ids:
            skills_result = await session.execute(
                select(TeamSkill).where(TeamSkill.id.in_(skill_ids))
            )
            for skill in skills_result.scalars().all():
                skill_map[skill.id] = skill.display_name or skill.name or skill.id

        return [
            {
                "id": log.id,
                "skill_id": log.skill_id,
                "deployment_id": log.deployment_id,
                "user_id": log.user_id,
                "user_display_name": user_map.get(log.user_id, log.user_id),
                "skill_display_name": skill_map.get(log.skill_id, log.skill_id),
                "source": log.source,
                "action": log.action,
                "version": log.version,
                "diff_summary": log.diff_summary,
                "change_items": _parse_change_items(log.change_items),
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in rows
        ]


def _parse_change_items(raw: Optional[str]) -> List[Dict[str, Any]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
        return data if isinstance(data, list) else []
    except Exception:
        return []


async def get_project_team_id(project_id: str) -> Optional[str]:
    async with async_session_factory() as session:
        project = await session.get(Project, project_id)
        return project.team_id if project else None
