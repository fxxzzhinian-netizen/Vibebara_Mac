from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.project import (
    Project,
    ProjectPermissionPolicy,
    UserSkillDeployment,
)
from app.models.team import TeamMember
from app.models.user import User


PERMISSION_KEYS = (
    "add_skill",
    "remove_skill",
    "deploy_skill",
    "push_changes",
    "pull_updates",
    "merge_conflicts",
    "manage_tracking",
)

DEFAULT_MEMBER_PERMISSIONS = {key: True for key in PERMISSION_KEYS}
MANAGER_ROLES = {"owner", "admin"}


class ProjectPermissionError(Exception):
    status_code = 403


class ProjectNotFoundError(ProjectPermissionError):
    status_code = 404


class ProjectAccessDeniedError(ProjectPermissionError):
    status_code = 403


class DeploymentNotFoundError(ProjectPermissionError):
    status_code = 404


@dataclass(frozen=True)
class ProjectPermissionContext:
    project_id: str
    team_id: str
    user_id: str
    role: str
    member_permissions: dict[str, bool]
    effective_permissions: dict[str, bool]
    can_manage: bool


def normalize_member_permissions(
    permissions: Mapping[str, Any] | None,
    *,
    strict: bool = False,
) -> dict[str, bool]:
    """Return a complete, boolean-only policy in the canonical key order."""
    if permissions is None:
        if strict:
            raise ValueError("member_permissions is required")
        return DEFAULT_MEMBER_PERMISSIONS.copy()
    if not isinstance(permissions, Mapping):
        if strict:
            raise ValueError("member_permissions must be an object")
        return DEFAULT_MEMBER_PERMISSIONS.copy()

    supplied_keys = set(permissions)
    expected_keys = set(PERMISSION_KEYS)
    if strict and supplied_keys != expected_keys:
        missing = sorted(expected_keys - supplied_keys)
        unknown = sorted(supplied_keys - expected_keys)
        parts = []
        if missing:
            parts.append(f"missing keys: {', '.join(missing)}")
        if unknown:
            parts.append(f"unknown keys: {', '.join(unknown)}")
        raise ValueError("; ".join(parts))

    normalized = DEFAULT_MEMBER_PERMISSIONS.copy()
    for key in PERMISSION_KEYS:
        if key not in permissions:
            continue
        value = permissions[key]
        if type(value) is not bool:
            if strict:
                raise ValueError(f"permission '{key}' must be a boolean")
            continue
        normalized[key] = value
    return normalized


def resolve_effective_permissions(
    role: str,
    member_permissions: Mapping[str, Any] | None,
) -> dict[str, bool]:
    if role in MANAGER_ROLES:
        return DEFAULT_MEMBER_PERMISSIONS.copy()
    return normalize_member_permissions(member_permissions)


async def _load_access_context(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> ProjectPermissionContext:
    project = await session.get(Project, project_id)
    if project is None:
        raise ProjectNotFoundError("项目不存在")

    role = await session.scalar(
        select(TeamMember.role).where(
            TeamMember.team_id == project.team_id,
            TeamMember.user_id == user_id,
        )
    )
    if role is None:
        raise ProjectAccessDeniedError("无权访问该项目")

    policy = await session.get(ProjectPermissionPolicy, project_id)
    configured = normalize_member_permissions(
        policy.member_permissions if policy else None
    )
    can_manage = role in MANAGER_ROLES
    return ProjectPermissionContext(
        project_id=project.id,
        team_id=project.team_id,
        user_id=user_id,
        role=role,
        member_permissions=configured,
        effective_permissions=resolve_effective_permissions(role, configured),
        can_manage=can_manage,
    )


async def require_project_access(
    project_id: str,
    user_id: str,
) -> ProjectPermissionContext:
    async with async_session_factory() as session:
        return await _load_access_context(session, project_id, user_id)


async def require_project_manager(
    project_id: str,
    user_id: str,
) -> ProjectPermissionContext:
    context = await require_project_access(project_id, user_id)
    if not context.can_manage:
        raise ProjectAccessDeniedError("仅项目所属团队的 owner/admin 可执行此操作")
    return context


async def require_project_permission(
    project_id: str,
    user_id: str,
    permission: str,
) -> ProjectPermissionContext:
    if permission not in PERMISSION_KEYS:
        raise ValueError(f"unknown project permission: {permission}")
    context = await require_project_access(project_id, user_id)
    if not context.effective_permissions[permission]:
        raise ProjectAccessDeniedError(f"缺少项目权限: {permission}")
    return context


async def require_deployment_access(
    deployment_id: str,
    user_id: str,
    permission: str | None = None,
    *,
    require_owner: bool = True,
) -> ProjectPermissionContext:
    """Resolve the deployment's project and recheck current team membership."""
    async with async_session_factory() as session:
        deployment = await session.get(UserSkillDeployment, deployment_id)
        if deployment is None:
            raise DeploymentNotFoundError("部署记录不存在")

        context = await _load_access_context(
            session,
            deployment.project_id,
            user_id,
        )
        if require_owner and deployment.user_id != user_id:
            raise ProjectAccessDeniedError("无权操作其他用户的部署")
        if permission is not None:
            if permission not in PERMISSION_KEYS:
                raise ValueError(f"unknown project permission: {permission}")
            if not context.effective_permissions[permission]:
                raise ProjectAccessDeniedError(f"缺少项目权限: {permission}")
        return context


async def get_project_permissions(
    project_id: str,
    user_id: str,
) -> dict[str, Any]:
    async with async_session_factory() as session:
        context = await _load_access_context(session, project_id, user_id)
        policy = await session.get(ProjectPermissionPolicy, project_id)
        updater = (
            await session.get(User, policy.updated_by)
            if policy and policy.updated_by
            else None
        )
        return {
            "project_id": project_id,
            "member_permissions": context.member_permissions,
            "effective_permissions": context.effective_permissions,
            "role": context.role,
            "can_manage": context.can_manage,
            "updated_by": policy.updated_by if policy else None,
            "updated_by_name": (
                (updater.display_name or updater.username) if updater else None
            ),
            "updated_at": (
                policy.updated_at.isoformat()
                if policy and policy.updated_at
                else None
            ),
        }


async def update_project_permissions(
    project_id: str,
    user_id: str,
    member_permissions: Mapping[str, Any],
) -> dict[str, Any]:
    normalized = normalize_member_permissions(member_permissions, strict=True)
    async with async_session_factory() as session:
        context = await _load_access_context(session, project_id, user_id)
        if not context.can_manage:
            raise ProjectAccessDeniedError(
                "仅项目所属团队的 owner/admin 可更新项目权限"
            )

        policy = await session.get(ProjectPermissionPolicy, project_id)
        if policy is None:
            policy = ProjectPermissionPolicy(
                project_id=project_id,
                member_permissions=normalized,
                updated_by=user_id,
            )
            session.add(policy)
        else:
            policy.member_permissions = normalized
            policy.updated_by = user_id
        await session.commit()
        await session.refresh(policy)

        updater = await session.get(User, user_id)
        return {
            "project_id": project_id,
            "member_permissions": normalized,
            "effective_permissions": DEFAULT_MEMBER_PERMISSIONS.copy(),
            "role": context.role,
            "can_manage": True,
            "updated_by": user_id,
            "updated_by_name": (
                (updater.display_name or updater.username) if updater else None
            ),
            "updated_at": (
                policy.updated_at.isoformat() if policy.updated_at else None
            ),
        }
