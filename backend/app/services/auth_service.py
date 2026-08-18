"""
轻量认证服务 — 密码哈希 + 统一有状态凭据（auth_tokens：session / pat）

登录态（session）与长期无头凭据（pat）同表、同一条校验路径（verify_credential）：
sha256(明文) 命中 token_hash → 未吊销 + 未过期 → 返回 user_id。
"""

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session_factory
from app.models.auth_token import AuthToken
from app.models.device import Device
from app.models.project import UserSkillDeployment
from app.models.user import User
from app.services import device_service

logger = logging.getLogger(__name__)

# 凭据明文前缀：仅作日志辨识 + 快速拒绝，校验只认 token_hash，不依赖前缀。
_SESSION_PREFIX = "vhs_"  # 登录态
_PAT_PREFIX = "vhk_"      # 长期无头凭据（沿用历史 API Key 前缀，CLI 文档一致）


@dataclass(frozen=True)
class AuthCredential:
    token_id: str
    user_id: str
    kind: str
    device_id: Optional[str]


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return f"{salt}:{h.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if ":" not in stored:
        return False
    salt, expected = stored.split(":", 1)
    h = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 100_000)
    return hmac.compare_digest(h.hex(), expected)


def _hash_token(raw: str) -> str:
    """凭据明文 → sha256 hex（落库只存哈希）。token 为高熵随机，快速哈希足够。"""
    return hashlib.sha256(raw.encode()).hexdigest()


async def _create_session_token_in_session(
    session: AsyncSession,
    user_id: str,
    device_id: Optional[str],
) -> str:
    raw = f"{_SESSION_PREFIX}{secrets.token_urlsafe(32)}"
    session.add(
        AuthToken(
            user_id=user_id,
            device_id=device_id,
            token_hash=_hash_token(raw),
            kind="session",
            expires_at=datetime.utcnow()
            + timedelta(seconds=settings.SESSION_TOKEN_TTL_SECONDS),
        )
    )
    await session.flush()
    return raw


async def create_session_token(user_id: str, device_id: Optional[str] = None) -> str:
    """签发登录态凭据（kind=session，带过期）。返回明文（仅此一次可见）。"""
    async with async_session_factory() as session:
        raw = await _create_session_token_in_session(session, user_id, device_id)
        await session.commit()
    return raw


async def create_pat(
    user_id: str,
    name: str = "",
    expires_at: Optional[datetime] = None,
    device_id: Optional[str] = None,
) -> str:
    """签发设备绑定 PAT；重签仅轮换当前设备的 active PAT。"""
    raw = f"{_PAT_PREFIX}{secrets.token_urlsafe(32)}"
    now = datetime.utcnow()
    async with async_session_factory() as session:
        existing = (
            await session.execute(
                select(AuthToken).where(
                    AuthToken.user_id == user_id,
                    AuthToken.kind == "pat",
                    AuthToken.device_id == device_id,
                    AuthToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        for row in existing:
            row.revoked_at = now
            row.revoked_reason = "rotated"
        session.add(
            AuthToken(
                user_id=user_id,
                device_id=device_id,
                token_hash=_hash_token(raw),
                kind="pat",
                name=name or "",
                expires_at=expires_at,
            )
        )
        await session.commit()
    return raw


async def verify_credential(raw: str) -> Optional[str]:
    """统一校验：命中 token_hash 且未吊销、未过期 → user_id；否则 None。

    顺带节流刷新 last_used_at（距上次 > 5min 才写，降写放大）。
    session 与 pat 共用本路径，仅 expires_at 是否为空不同。
    """
    credential = await verify_credential_info(raw)
    return credential.user_id if credential else None


async def verify_credential_info(raw: str) -> Optional[AuthCredential]:
    """校验凭据并返回 token/device 上下文；设备被停用时凭据立即失效。"""
    if not raw:
        return None
    now = datetime.utcnow()
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(AuthToken).where(AuthToken.token_hash == _hash_token(raw))
            )
        ).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            return None
        if row.expires_at is not None and now > row.expires_at:
            return None
        if row.device_id:
            device = await session.get(Device, row.device_id)
            if (
                device is None
                or device.user_id != row.user_id
                or device.status != "active"
            ):
                return None
        if (
            row.last_used_at is None
            or (now - row.last_used_at).total_seconds() > 300
        ):
            row.last_used_at = now
            await session.commit()
        return AuthCredential(
            token_id=row.id,
            user_id=row.user_id,
            kind=row.kind,
            device_id=row.device_id,
        )


async def credential_failure_reason(raw: str) -> str:
    """仅在鉴权失败后查询可公开原因，帮助旧设备/CLI 给出明确提示。"""
    if not raw:
        return ""
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(AuthToken).where(AuthToken.token_hash == _hash_token(raw))
            )
        ).scalar_one_or_none()
        return row.revoked_reason if row and row.revoked_at is not None else ""


async def _issue_single_device_session(
    session: AsyncSession,
    user: User,
    client_uuid: str,
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    app_version: Optional[str] = None,
    agent_version: Optional[str] = None,
) -> tuple[str, str]:
    """调用方持有 User 行锁；切换唯一 active device 并签发新 session。"""
    device = await device_service.activate_device_for_login(
        session,
        user.id,
        client_uuid,
        platform=platform,
        hostname=hostname,
        app_version=app_version,
        agent_version=agent_version,
    )
    now = datetime.utcnow()
    # 所有旧交互会话失效；其他设备的 PAT/CI Key 同步失效。
    await session.execute(
        update(AuthToken)
        .where(
            AuthToken.user_id == user.id,
            AuthToken.revoked_at.is_(None),
            or_(
                AuthToken.kind == "session",
                AuthToken.device_id != device.id,
                AuthToken.device_id.is_(None),
            ),
        )
        .values(revoked_at=now, revoked_reason="signed_in_elsewhere")
    )
    # 升级前无 device_id 的部署记录归入首次登录设备，避免升级后全部消失。
    await session.execute(
        update(UserSkillDeployment)
        .where(
            UserSkillDeployment.user_id == user.id,
            UserSkillDeployment.device_id.is_(None),
        )
        .values(device_id=device.id)
    )
    raw = await _create_session_token_in_session(session, user.id, device.id)
    return raw, device.id


async def register(
    username: str,
    password: str,
    display_name: str = "",
    email: Optional[str] = None,
    invite_code: Optional[str] = None,
    bypass_invite: bool = False,
    client_uuid: str = "",
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    app_version: Optional[str] = None,
    agent_version: Optional[str] = None,
    issue_session: bool = True,
) -> dict:
    """注册新用户。

    INVITE_CODE_REQUIRED 开启时必须提供有效邀请码（bypass_invite 仅供
    种子用户等内部调用绕过）。邀请码消费与用户创建在同一事务内，
    注册失败回滚时不会浪费邀请码次数。
    """
    from app.services import invite_service

    async with async_session_factory() as session:
        existing = await session.execute(
            select(User).where(User.username == username)
        )
        if existing.scalar_one_or_none():
            return {"success": False, "error": "用户名已存在"}

        if email:
            dup_email = await session.execute(
                select(User).where(User.email == email)
            )
            if dup_email.scalar_one_or_none():
                return {"success": False, "error": "邮箱已被注册"}

        consumed_code: Optional[str] = None
        if settings.INVITE_CODE_REQUIRED and not bypass_invite:
            ok, code_or_error = await invite_service.consume_invite(
                session, invite_code or ""
            )
            if not ok:
                await session.rollback()
                return {"success": False, "error": code_or_error}
            consumed_code = code_or_error

        user = User(
            username=username,
            password_hash=_hash_password(password),
            display_name=display_name or username,
            email=email,
            invite_code_used=consumed_code,
        )
        session.add(user)
        await session.flush()
        new_user_id = user.id
        new_username = user.username
        token = ""
        device_id = ""
        if issue_session:
            token, device_id = await _issue_single_device_session(
                session,
                user,
                client_uuid,
                platform=platform,
                hostname=hostname,
                app_version=app_version,
                agent_version=agent_version,
            )
        await session.commit()

    return {
        "success": True,
        "token": token,
        "device_id": device_id,
        "user_id": new_user_id,
        "username": new_username,
    }


async def login(
    username: str,
    password: str,
    client_uuid: str,
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    app_version: Optional[str] = None,
    agent_version: Optional[str] = None,
) -> dict:
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == username).with_for_update()
        )
        user = result.scalar_one_or_none()
        if not user or not _verify_password(password, user.password_hash):
            return {"success": False, "error": "用户名或密码错误"}
        user_id = user.id
        resolved_username = user.username
        token, device_id = await _issue_single_device_session(
            session,
            user,
            client_uuid,
            platform=platform,
            hostname=hostname,
            app_version=app_version,
            agent_version=agent_version,
        )
        await session.commit()

    # 当前部署采用进程内 WS hub；新登录完成后主动关闭旧连接。
    try:
        from app.websocket.hub import close_user_connections

        await close_user_connections(user_id)
    except Exception:
        logger.exception("[auth/login] 关闭旧设备 WebSocket 失败")
    return {
        "success": True,
        "token": token,
        "device_id": device_id,
        "user_id": user_id,
        "username": resolved_username,
    }


async def get_user_by_id(user_id: str) -> Optional[User]:
    async with async_session_factory() as session:
        return await session.get(User, user_id)


async def update_profile(user_id: str, updates: Mapping[str, Any]) -> dict:
    """部分更新个人资料；调用方应传入 schema 的 exclude_unset 结果。"""
    allowed_fields = {
        "display_name",
        "email",
        "phone",
        "gender",
        "birthday",
        "locale",
        "location",
    }
    values = {key: value for key, value in updates.items() if key in allowed_fields}

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "error": "用户不存在"}

        email = values.get("email")
        if email:
            duplicate = (
                await session.execute(
                    select(User).where(
                        User.email == email,
                        User.id != user_id,
                    )
                )
            ).scalar_one_or_none()
            if duplicate:
                return {"success": False, "error": "该邮箱已被其他账号使用"}

        for field, value in values.items():
            setattr(user, field, value)
        if values:
            user.updated_at = datetime.utcnow()
        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            return {"success": False, "error": "该邮箱已被其他账号使用"}
        await session.refresh(user)
        return {"success": True, "user": user}


async def set_avatar_url(user_id: str, avatar_url: Optional[str]) -> dict:
    """写入或清空头像路径，并显式推进 updated_at 供客户端缓存刷新。"""
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "error": "用户不存在"}
        user.avatar_url = avatar_url
        user.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(user)
        return {"success": True, "user": user}


async def save_onboarding(
    user_id: str, dev_mode: str, favorite_tool: str
) -> dict:
    """保存首次登录引导选择并标记完成。"""
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "error": "用户不存在"}
        user.dev_mode = dev_mode
        user.favorite_tool = favorite_tool
        user.onboarded = True
        await session.commit()
    return {"success": True}


async def generate_api_key(user_id: str, device_id: Optional[str]) -> dict:
    """为当前 active 设备签发长期 API Key（PAT）。"""
    if not device_id:
        return {"success": False, "error": "当前会话未绑定设备，请重新登录"}
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "error": "用户不存在"}
        device = await session.get(Device, device_id)
        if not device or device.user_id != user_id or device.status != "active":
            return {"success": False, "error": "当前设备已失效，请重新登录"}
    raw_key = await create_pat(user_id, name="cli", device_id=device_id)
    return {"success": True, "api_key": raw_key}


async def has_active_api_key(user_id: str, device_id: Optional[str]) -> bool:
    """返回当前设备是否持有未吊销、未过期的 CLI PAT。"""
    if not device_id:
        return False
    now = datetime.utcnow()
    async with async_session_factory() as session:
        row = (
            await session.execute(
                select(AuthToken.id)
                .where(
                    AuthToken.user_id == user_id,
                    AuthToken.kind == "pat",
                    AuthToken.device_id == device_id,
                    AuthToken.revoked_at.is_(None),
                    or_(
                        AuthToken.expires_at.is_(None),
                        AuthToken.expires_at >= now,
                    ),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        return row is not None


async def revoke_credential(token_id: str, reason: str = "logout") -> bool:
    async with async_session_factory() as session:
        row = await session.get(AuthToken, token_id)
        if not row or row.revoked_at is not None:
            return False
        row.revoked_at = datetime.utcnow()
        row.revoked_reason = reason
        await session.commit()
        return True


# =========================================================================
# SKILL 市场：角色与权限判定
# =========================================================================


def is_seed_user(user: Optional[User]) -> bool:
    """种子用户（DAIL/DAIL2）：始终具备审核 + 创建平台管理员权限，自己发布免审核。"""
    return bool(user and user.username in settings.MARKET_SEED_REVIEWERS)


def is_reviewer(user: Optional[User]) -> bool:
    """可审核 SKILL 市场发布 = 种子用户 或 平台管理员。"""
    return bool(user and (is_seed_user(user) or getattr(user, "is_platform_admin", False)))


def can_manage_admins(user: Optional[User]) -> bool:
    """可创建/移除平台管理员 = 仅种子用户。"""
    return is_seed_user(user)


async def list_platform_admins() -> list[dict]:
    """返回全部平台管理员（含种子用户标记），供管理界面展示。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User)
            .where(User.is_platform_admin.is_(True))
            .order_by(User.created_at)
        )
        admins = list(result.scalars().all())
    return [
        {
            "id": u.id,
            "username": u.username,
            "display_name": u.display_name,
            "is_seed_user": is_seed_user(u),
        }
        for u in admins
    ]


async def grant_platform_admin(username: str) -> dict:
    """按用户名授予平台管理员。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(User).where(User.username == username)
        )
        user = result.scalar_one_or_none()
        if not user:
            return {"success": False, "error": "用户不存在"}
        if user.is_platform_admin:
            return {"success": False, "error": "该用户已是平台管理员"}
        user.is_platform_admin = True
        await session.commit()
        return {
            "success": True,
            "admin": {
                "id": user.id,
                "username": user.username,
                "display_name": user.display_name,
                "is_seed_user": is_seed_user(user),
            },
        }


async def revoke_platform_admin(user_id: str) -> dict:
    """移除某用户的平台管理员（种子用户不可移除）。"""
    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user:
            return {"success": False, "error": "用户不存在"}
        if is_seed_user(user):
            return {"success": False, "error": "种子用户为内置管理员，不可移除"}
        user.is_platform_admin = False
        await session.commit()
        return {"success": True}
