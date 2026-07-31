"""方案 B · M5-b 设备身份端点单测（设计 §3 / §4.2.1 / §8）。

两层验证：
  A. 路由鉴权与归属（TestClient + 打桩服务/鉴权，**不连 DB**，始终运行）：
     · POST /devices/register 缺 Bearer → 401；带 Bearer → 200 且返回服务端铸造的
       deviceId（camelCase 输出），客户端入参里的 deviceId 一律被忽略（防伪冒）。
     · DELETE /devices/{id} 他人设备 → 403（归属校验）；本人 → 200 revoked。
     · 注册端点**绝不**返回配对令牌（守 M2 决议④）。
  B. 服务层铸造 / 幂等 / 越权（**真实 MySQL**，环境受限时跳过并打印原因）：
     · 同机同用户重复注册 → 同一 device_id（幂等）；
     · 同机不同用户注册 → 不同 device_id（多用户同机互不串扰）；
     · revoke 他人设备 → forbidden（越权拦截）。

可直接运行：`python -m tests.test_devices`（无需 pytest，亦兼容 pytest）。
"""

import asyncio
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import auth_service  # noqa: E402
from app.services import device_service  # noqa: E402


# =====================================================================
# A. 路由鉴权与归属（不连 DB）
# =====================================================================

def _build_client():
    from fastapi.testclient import TestClient
    import app.main as m

    m.settings.DEPLOYMENT_MODE = "local"
    return TestClient(m.create_app())


def _install_router_stubs():
    token_user = {"tok-a": "user-a", "tok-b": "user-b"}

    async def fake_verify(token):
        return token_user.get(token)

    async def fake_register(user_id, client_uuid, platform=None, hostname=None,
                            app_version=None, agent_version=None):
        # 服务端铸造 device_id（与客户端入参无关，防伪冒）。
        return {
            "success": True,
            "device": {
                "device_id": f"minted-{user_id}-{client_uuid}",
                "client_uuid": client_uuid,
                "platform": platform or "",
                "hostname": hostname,
                "app_version": app_version,
                "agent_version": agent_version,
                "status": "active",
                "last_seen_at": "2026-06-02T00:00:00",
                "last_sync_at": None,
                "created_at": "2026-06-02T00:00:00",
            },
        }

    # 设备 owner 映射：dev-a 属 user-a。
    device_owner = {"dev-a": "user-a"}

    async def fake_revoke(user_id, device_id):
        owner = device_owner.get(device_id)
        if owner is None:
            return {"success": False, "error": "设备不存在", "code": "not_found"}
        if owner != user_id:
            return {"success": False, "error": "无权操作他人设备", "code": "forbidden"}
        return {"success": True, "device_id": device_id, "status": "revoked"}

    saved = {
        "verify": auth_service.verify_credential,
        "register": device_service.register_device,
        "revoke": device_service.revoke_device,
    }
    auth_service.verify_credential = fake_verify
    device_service.register_device = fake_register
    device_service.revoke_device = fake_revoke
    return saved


def _restore_router_stubs(saved):
    auth_service.verify_credential = saved["verify"]
    device_service.register_device = saved["register"]
    device_service.revoke_device = saved["revoke"]


def test_register_requires_bearer_and_mints_server_side():
    client = _build_client()
    saved = _install_router_stubs()
    try:
        # 缺 Bearer → 401
        r = client.post("/api/v1/devices/register", json={"clientUuid": "cuid-1"})
        assert r.status_code == 401, r.text

        # 带 Bearer → 200，返回服务端铸造的 deviceId（忽略客户端伪造的 deviceId）。
        r = client.post(
            "/api/v1/devices/register",
            json={"clientUuid": "cuid-1", "platform": "win32",
                  "deviceId": "ATTACKER-FORGED", "appVersion": "1.0.0"},
            headers={"Authorization": "Bearer tok-a"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        dev = body["device"]
        assert dev["deviceId"] == "minted-user-a-cuid-1", dev
        assert dev["deviceId"] != "ATTACKER-FORGED"
        assert dev["clientUuid"] == "cuid-1"
        assert dev["status"] == "active"
        # 守 M2 决议④：注册响应绝不含配对令牌字段。
        assert "pairingToken" not in dev and "pairing_token" not in dev
        assert "pairingToken" not in body and "pairing_token" not in body
    finally:
        _restore_router_stubs(saved)


def test_revoke_ownership_guard():
    client = _build_client()
    saved = _install_router_stubs()
    try:
        # 缺 Bearer → 401
        r = client.delete("/api/v1/devices/dev-a")
        assert r.status_code == 401, r.text

        # 他人设备（dev-a 属 user-a，但用 user-b 的 token）→ 403
        r = client.delete(
            "/api/v1/devices/dev-a", headers={"Authorization": "Bearer tok-b"}
        )
        assert r.status_code == 403, r.text

        # 不存在的设备 → 404
        r = client.delete(
            "/api/v1/devices/dev-zzz", headers={"Authorization": "Bearer tok-a"}
        )
        assert r.status_code == 404, r.text

        # 本人设备 → 200 revoked
        r = client.delete(
            "/api/v1/devices/dev-a", headers={"Authorization": "Bearer tok-a"}
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["deviceId"] == "dev-a"
        assert body["status"] == "revoked"
    finally:
        _restore_router_stubs(saved)


def test_devices_router_mounted_in_both_modes():
    """devices 路由在 local / cloud 均挂载（设计 §7.3）。"""
    import app.main as m

    for mode in ("local", "cloud"):
        m.settings.DEPLOYMENT_MODE = mode
        app = m.create_app()
        paths = [getattr(r, "path", "") for r in app.routes]
        assert any(p.startswith("/api/v1/devices") for p in paths), (mode, paths)


# =====================================================================
# B. 服务层铸造 / 幂等 / 越权（真实 MySQL，环境受限时跳过）
# =====================================================================

async def _db_reachable() -> bool:
    try:
        from sqlalchemy import text
        from app.core.database import engine

        async with engine.connect() as c:
            await c.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _ensure_tables() -> None:
    from app.core.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _service_idempotency_and_ownership() -> None:
    from sqlalchemy import delete
    from app.core.database import async_session_factory
    from app.models.device import Device
    from app.models.user import User



    # 两个临时用户
    # 本测试验证设备服务，不验证邀请码；显式使用受信任的测试注册入口。
    u1 = await auth_service.register(
        f"dev-test-{uuid.uuid4().hex[:8]}", "pw", bypass_invite=True
    )
    u2 = await auth_service.register(
        f"dev-test-{uuid.uuid4().hex[:8]}", "pw", bypass_invite=True
    )
    assert u1.get("success") and u2.get("success"), (u1, u2)
    uid1, uid2 = u1["user_id"], u2["user_id"]
    client_uuid = f"cuid-{uuid.uuid4().hex}"

    created_device_ids = []
    try:
        # 铸造：首次注册 → 服务端铸造 device_id（uuid4）
        r1 = await device_service.register_device(uid1, client_uuid, platform="win32")
        assert r1["success"], r1
        did1 = r1["device"]["device_id"]
        assert did1 and did1 != client_uuid, "device_id 应服务端铸造、非 client_uuid"
        assert len(did1) == 36, "device_id 应为 uuid4"
        created_device_ids.append(did1)

        # 幂等：同机同用户重复注册 → 同一 device_id
        r1b = await device_service.register_device(
            uid1, client_uuid, platform="win32", app_version="2.0.0"
        )
        assert r1b["device"]["device_id"] == did1, "同机同用户应幂等命中同一行"
        assert r1b["device"]["app_version"] == "2.0.0", "元数据应刷新"

        # 多用户同机：同 client_uuid 不同用户 → 不同 device_id
        r2 = await device_service.register_device(uid2, client_uuid, platform="win32")
        did2 = r2["device"]["device_id"]
        assert did2 != did1, "同机不同账号应产生独立设备身份"
        created_device_ids.append(did2)

        # 越权：user2 撤销 user1 的设备 → forbidden
        rev_bad = await device_service.revoke_device(uid2, did1)
        assert rev_bad["success"] is False and rev_bad.get("code") == "forbidden"

        # 归属：user1 撤销自己的设备 → 成功 revoked
        rev_ok = await device_service.revoke_device(uid1, did1)
        assert rev_ok["success"] and rev_ok["status"] == "revoked"

        # 重新注册被撤销设备 → 重新激活（status=active）+ 同一 device_id
        r1c = await device_service.register_device(uid1, client_uuid)
        assert r1c["device"]["device_id"] == did1
        assert r1c["device"]["status"] == "active", "重新注册应重新激活已撤销设备"
    finally:
        # 清理
        async with async_session_factory() as session:
            for did in created_device_ids:
                await session.execute(delete(Device).where(Device.id == did))
            for uid in (uid1, uid2):
                await session.execute(delete(User).where(User.id == uid))
            await session.commit()


async def _db_main() -> str:
    """单事件循环内完成「可达探测 → 建表 → 测试 → 释放引擎」。

    Windows proactor 下连接池不能跨 asyncio.run 复用，故 reachability 与测试必须同循环；
    末尾 engine.dispose() 释放池连接，避免进程退出时在已关闭 loop 上 rollback 报错。
    """
    from app.core.database import engine

    try:
        if not await _db_reachable():
            return "skip"
        await _ensure_tables()
        await _service_idempotency_and_ownership()
        return "ok"
    finally:
        await engine.dispose()


def test_service_layer_db():
    result = asyncio.run(_db_main())
    if result == "skip":
        print("  [skip] 服务层 DB 测试：MySQL 不可达（root@localhost:3306/cowork）")


def _run_all():
    tests = [
        test_register_requires_bearer_and_mints_server_side,
        test_revoke_ownership_guard,
        test_devices_router_mounted_in_both_modes,
        test_service_layer_db,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} device tests passed (DB 层视环境跳过)。")


if __name__ == "__main__":
    _run_all()
