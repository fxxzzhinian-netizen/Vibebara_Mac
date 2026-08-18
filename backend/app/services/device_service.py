"""设备身份服务（方案 B · M5-b 设备身份地基）。

依据 `docs/archive/desktop-migration/M5-平台安装状态-多用户多机设计.md` §3：
  · register_device —— 按 `(user_id, client_uuid)` 幂等 upsert，服务端铸造规范 device_id；
    **只铸造设备身份、绝不签发配对令牌**（守 M2 决议④）。
  · list_devices —— 列举「我的」设备（默认含 revoked，便于前端展示/管理）。
  · revoke_device —— 软撤销（status=revoked，不删行），带归属校验防越权。

安全（设计 §3.4 / §8）：device_id 非鉴权凭证；归属校验（device.user_id == 当前用户）
统一在调用方（路由 Depends Bearer + 本服务的 owner 校验）完成。
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.models.device import Device

logger = logging.getLogger(__name__)


def _device_to_info(device: Device) -> Dict[str, Any]:
    """Device ORM → DeviceInfo 可消费的 dict（python 字段名，路由用 DeviceInfo(**) 包装）。"""
    return {
        "device_id": device.id,
        "client_uuid": device.client_uuid,
        "platform": device.platform or "",
        "hostname": device.hostname,
        "app_version": device.app_version,
        "agent_version": device.agent_version,
        "status": device.status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "last_sync_at": device.last_sync_at.isoformat() if device.last_sync_at else None,
        "created_at": device.created_at.isoformat() if device.created_at else None,
    }


async def activate_device_for_login(
    session: AsyncSession,
    user_id: str,
    client_uuid: str,
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    app_version: Optional[str] = None,
    agent_version: Optional[str] = None,
) -> Device:
    """在登录事务内激活唯一设备；调用方必须先锁定对应 User 行。"""
    cuid = (client_uuid or "").strip()
    if not cuid:
        raise ValueError("缺少 clientUuid")

    device = (
        await session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.client_uuid == cuid,
            )
        )
    ).scalar_one_or_none()
    now = datetime.utcnow()
    if device is None:
        device = Device(user_id=user_id, client_uuid=cuid)
        session.add(device)
        await session.flush()

    await session.execute(
        update(Device)
        .where(Device.user_id == user_id, Device.id != device.id)
        .values(status="revoked", revoked_at=now)
    )
    device.platform = (platform or device.platform or "")[:16]
    if hostname is not None:
        device.hostname = hostname
    if app_version is not None:
        device.app_version = app_version
    if agent_version is not None:
        device.agent_version = agent_version
    device.status = "active"
    device.revoked_at = None
    device.last_seen_at = now
    await session.flush()
    return device


async def get_active_device_id(user_id: str) -> Optional[str]:
    async with async_session_factory() as session:
        return (
            await session.execute(
                select(Device.id)
                .where(Device.user_id == user_id, Device.status == "active")
                .order_by(Device.last_seen_at.desc(), Device.updated_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def register_device(
    user_id: str,
    client_uuid: str,
    platform: Optional[str] = None,
    hostname: Optional[str] = None,
    app_version: Optional[str] = None,
    agent_version: Optional[str] = None,
) -> Dict[str, Any]:
    """按 (user_id, client_uuid) 幂等 upsert 设备身份；铸造/返回规范 device_id。

    幂等：同机同用户重复注册命中同一行、返回同一 device_id（设计 §3.1）。
    该端点只刷新当前 active 设备。被挤下线的设备必须重新输入密码登录，
    不能拿旧 Bearer 自助恢复。
    """
    cuid = (client_uuid or "").strip()
    if not cuid:
        return {"success": False, "error": "缺少 clientUuid"}

    async with async_session_factory() as session:
        result = await session.execute(
            select(Device).where(
                Device.user_id == user_id, Device.client_uuid == cuid
            )
        )
        device = result.scalar_one_or_none()
        now = datetime.utcnow()

        if device is None:
            return {"success": False, "error": "设备尚未通过登录激活", "code": "inactive"}
        else:
            if device.status != "active":
                return {
                    "success": False,
                    "error": "账号已在另一台设备登录，请重新登录",
                    "code": "signed_in_elsewhere",
                }
            # 幂等命中：仅刷新当前设备元数据与心跳。
            if platform is not None:
                device.platform = platform[:16]
            if hostname is not None:
                device.hostname = hostname
            if app_version is not None:
                device.app_version = app_version
            if agent_version is not None:
                device.agent_version = agent_version
            device.last_seen_at = now

        await session.commit()
        await session.refresh(device)
        return {"success": True, "device": _device_to_info(device)}


async def list_devices(user_id: str) -> List[Dict[str, Any]]:
    """列举「我的」设备（按创建时间升序）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            select(Device)
            .where(Device.user_id == user_id)
            .order_by(Device.created_at.asc())
        )
        return [_device_to_info(d) for d in result.scalars().all()]


async def revoke_device(user_id: str, device_id: str) -> Dict[str, Any]:
    """软撤销设备（status=revoked，不删行）。

    归属校验：仅设备归属当前用户才可撤销；否则视为越权（返回 forbidden 标记，
    路由层转 403）。设备不存在 → not_found（路由层转 404）。
    """
    async with async_session_factory() as session:
        device = await session.get(Device, device_id)
        if device is None:
            return {"success": False, "error": "设备不存在", "code": "not_found"}
        if device.user_id != user_id:
            return {"success": False, "error": "无权操作他人设备", "code": "forbidden"}

        device.status = "revoked"
        device.revoked_at = datetime.utcnow()
        await session.commit()
        return {"success": True, "device_id": device_id, "status": "revoked"}
