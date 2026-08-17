"""统一有状态凭据（auth_tokens）单测 —— Token 根治。

两层：
  A. gate 接线（不连 DB，始终运行）：get_current_user_id 走 verify_credential，
     命中返回 user_id；None / 缺失 → 401。
  B. 服务层 roundtrip（真实 MySQL，环境受限时跳过并打印原因）：
     session/pat 签发→校验命中；未知/空/过期/吊销→None；PAT 重签发轮换旧 key；
     last_used_at 节流刷新。

可直接运行：`python -m tests.test_auth_tokens`（无需 pytest，亦兼容 pytest）。
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import HTTPException  # noqa: E402

import app.services.auth_service as auth_service  # noqa: E402
from app.api.auth import get_current_user_id  # noqa: E402


# =====================================================================
# A. gate 接线（不连 DB，始终运行）
# =====================================================================

def test_gate_uses_verify_credential():
    saved = auth_service.verify_credential

    async def fake_vc(raw):
        return "user-x" if raw == "good" else None

    auth_service.verify_credential = fake_vc
    try:
        # 命中（带 Bearer 前缀 / 裸串均可）
        assert asyncio.run(get_current_user_id("Bearer good")) == "user-x"
        assert asyncio.run(get_current_user_id("good")) == "user-x"

        # 无效凭据 → 401
        try:
            asyncio.run(get_current_user_id("Bearer bad"))
            assert False, "无效凭据应抛 401"
        except HTTPException as e:
            assert e.status_code == 401

        # 缺失 Authorization → 401
        try:
            asyncio.run(get_current_user_id(None))
            assert False, "缺失凭据应抛 401"
        except HTTPException as e:
            assert e.status_code == 401
    finally:
        auth_service.verify_credential = saved


# =====================================================================
# B. 服务层 roundtrip（真实 DB，环境受限时跳过）
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


async def _service_roundtrip() -> None:
    from sqlalchemy import delete, select
    from app.core.database import async_session_factory
    from app.models.auth_token import AuthToken
    from app.models.user import User

    reg = await auth_service.register(
        f"tok-test-{uuid.uuid4().hex[:8]}", "pw", bypass_invite=True
    )
    assert reg.get("success"), reg
    uid = reg["user_id"]

    try:
        # register 已签发 session token？register 返回 token，校验命中
        assert reg["token"].startswith("vhs_"), reg["token"]
        assert await auth_service.verify_credential(reg["token"]) == uid

        # 显式 session 签发 → 校验命中
        sess = await auth_service.create_session_token(uid)
        assert sess.startswith("vhs_")
        assert await auth_service.verify_credential(sess) == uid

        # 尚未签发 PAT 时，CLI 状态为未生成
        assert await auth_service.has_active_api_key(uid) is False

        # PAT 签发（无过期）→ 校验命中
        pat1 = await auth_service.create_pat(uid, name="cli")
        assert pat1.startswith("vhk_")
        assert await auth_service.verify_credential(pat1) == uid
        assert await auth_service.has_active_api_key(uid) is True

        # 未知 / 空 → None
        assert await auth_service.verify_credential("vhk_does-not-exist") is None
        assert await auth_service.verify_credential("") is None

        # PAT 重签发 = 轮换旧 PAT（旧失效、新有效）
        pat2 = await auth_service.create_pat(uid, name="cli")
        assert await auth_service.verify_credential(pat1) is None
        assert await auth_service.verify_credential(pat2) == uid

        # 过期 session → None
        async with async_session_factory() as session:
            session.add(AuthToken(
                user_id=uid,
                token_hash=auth_service._hash_token("vhs_expired-xyz"),
                kind="session",
                expires_at=datetime.utcnow() - timedelta(seconds=10),
            ))
            await session.commit()
        assert await auth_service.verify_credential("vhs_expired-xyz") is None

        # 吊销行 → None
        async with async_session_factory() as session:
            session.add(AuthToken(
                user_id=uid,
                token_hash=auth_service._hash_token("vhk_revoked-xyz"),
                kind="pat",
                revoked_at=datetime.utcnow(),
            ))
            await session.commit()
        assert await auth_service.verify_credential("vhk_revoked-xyz") is None

        # last_used_at 刷新（sess 已被校验过 → 非空）
        async with async_session_factory() as session:
            row = (await session.execute(
                select(AuthToken).where(
                    AuthToken.token_hash == auth_service._hash_token(sess)
                )
            )).scalar_one()
            assert row.last_used_at is not None
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(AuthToken).where(AuthToken.user_id == uid)
            )
            await session.execute(delete(User).where(User.id == uid))
            await session.commit()


async def _db_main() -> str:
    """单事件循环内完成「可达探测 → 建表 → 测试 → 释放引擎」。

    与 test_devices 同模式：Windows proactor 下连接池不能跨 asyncio.run 复用，
    reachability 与测试必须同循环；末尾 dispose 释放池连接。
    """
    from app.core.database import engine

    try:
        if not await _db_reachable():
            return "skip"
        await _ensure_tables()
        await _service_roundtrip()
        return "ok"
    finally:
        await engine.dispose()


def test_service_layer_db():
    result = asyncio.run(_db_main())
    if result == "skip":
        print("  [skip] 服务层 DB 测试：MySQL 不可达")


def _run_all():
    tests = [
        test_gate_uses_verify_credential,
        test_service_layer_db,
    ]
    for t in tests:
        t()
        print(f"  PASS  {t.__name__}")
    print(f"\nAll {len(tests)} auth-token tests passed (DB 层视环境跳过)。")


if __name__ == "__main__":
    _run_all()
