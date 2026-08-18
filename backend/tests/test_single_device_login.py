"""单账号单设备、设备绑定 PAT 与部署隔离的真实数据库回归测试。"""

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import delete, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import (  # noqa: E402
    _migrate_add_columns,
    async_session_factory,
    engine,
    init_db,
)
from app.models.auth_token import AuthToken  # noqa: E402
from app.models.device import Device  # noqa: E402
from app.models.project import Project, UserSkillDeployment  # noqa: E402
from app.models.team import Team, TeamMember  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import auth_service, device_service, project_service  # noqa: E402


async def _database_available() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _exercise_single_device_policy() -> None:
    suffix = uuid.uuid4().hex[:10]
    username = f"single-device-{suffix}"
    client_a = f"client-a-{suffix}"
    client_b = f"client-b-{suffix}"
    created: dict[str, str] = {}

    registration = await auth_service.register(
        username,
        "pw",
        bypass_invite=True,
        client_uuid=client_a,
        platform="win32",
    )
    assert registration["success"], registration
    user_id = registration["user_id"]
    device_a = registration["device_id"]
    session_a = registration["token"]
    created["user"] = user_id

    try:
        pat_a = await auth_service.create_pat(
            user_id, name="cli", device_id=device_a
        )

        # 同设备重新登录：旧 session 重签，当前设备 PAT 保留。
        same_device = await auth_service.login(
            username, "pw", client_a, platform="win32"
        )
        assert await auth_service.verify_credential(session_a) is None
        assert await auth_service.verify_credential(pat_a) == user_id

        # 新设备登录：旧设备 session 与 PAT 一并失效，register 无法自助恢复。
        switched = await auth_service.login(
            username, "pw", client_b, platform="darwin"
        )
        device_b = switched["device_id"]
        assert await auth_service.verify_credential(same_device["token"]) is None
        assert await auth_service.verify_credential(pat_a) is None
        assert await auth_service.verify_credential(switched["token"]) == user_id
        assert (
            await auth_service.credential_failure_reason(same_device["token"])
            == "signed_in_elsewhere"
        )
        denied = await device_service.register_device(user_id, client_a)
        assert denied["success"] is False
        assert denied["code"] == "signed_in_elsewhere"

        # 构造两台设备各自的同一项目部署，当前设备只能读取自己的路径/hash。
        team_id = str(uuid.uuid4())
        project_id = str(uuid.uuid4())
        skill_id = f"skill-{suffix}"
        created.update(team=team_id, project=project_id, skill=skill_id)
        async with async_session_factory() as session:
            session.add(
                Team(
                    id=team_id,
                    name=f"team-{suffix}",
                    owner_id=user_id,
                    invite_code=f"T{suffix[:8]}",
                )
            )
            await session.flush()
            session.add(TeamMember(team_id=team_id, user_id=user_id, role="owner"))
            session.add(
                Project(
                    id=project_id,
                    team_id=team_id,
                    name=f"project-{suffix}",
                    created_by=user_id,
                )
            )
            await session.flush()
            # 部分本地历史库仍保留 deployment -> skill_packages 旧外键；
            # 本测试只验证设备查询维度，不测试 Skill FK 迁移。
            await session.execute(text("SET FOREIGN_KEY_CHECKS=0"))
            session.add_all(
                [
                    UserSkillDeployment(
                        user_id=user_id,
                        device_id=device_a,
                        project_id=project_id,
                        team_skill_id=skill_id,
                        skill_name=skill_id,
                        tool_type="cursor",
                        deploy_path="C:/device-a",
                        install_path="C:/device-a/.cursor/skills/test",
                        repo_hash="hash-a",
                    ),
                    UserSkillDeployment(
                        user_id=user_id,
                        device_id=device_b,
                        project_id=project_id,
                        team_skill_id=skill_id,
                        skill_name=skill_id,
                        tool_type="cursor",
                        deploy_path="/device-b",
                        install_path="/device-b/.cursor/skills/test",
                        repo_hash="hash-b",
                    ),
                ]
            )
            await session.flush()
            await session.execute(text("SET FOREIGN_KEY_CHECKS=1"))
            await session.commit()

        deployments_b = await project_service.list_user_deployments(user_id)
        assert [item["device_id"] for item in deployments_b] == [device_b]
        assert deployments_b[0]["repo_hash"] == "hash-b"

        await auth_service.login(username, "pw", client_a, platform="win32")
        deployments_a = await project_service.list_user_deployments(user_id)
        assert [item["device_id"] for item in deployments_a] == [device_a]
        assert deployments_a[0]["repo_hash"] == "hash-a"

        # 并发登录由 User 行锁串行化；最终只能有一个 session 对应 active device。
        concurrent = await asyncio.gather(
            auth_service.login(username, "pw", f"client-c-{suffix}"),
            auth_service.login(username, "pw", f"client-d-{suffix}"),
        )
        valid = [
            await auth_service.verify_credential(result["token"])
            for result in concurrent
        ]
        assert sum(value == user_id for value in valid) == 1
    finally:
        async with async_session_factory() as session:
            if created.get("project"):
                await session.execute(
                    delete(UserSkillDeployment).where(
                        UserSkillDeployment.user_id == user_id
                    )
                )
                await session.execute(
                    delete(Project).where(Project.id == created["project"])
                )
                await session.execute(
                    delete(TeamMember).where(TeamMember.team_id == created["team"])
                )
                await session.execute(
                    delete(Team).where(Team.id == created["team"])
                )
            await session.execute(
                delete(AuthToken).where(AuthToken.user_id == user_id)
            )
            await session.execute(delete(Device).where(Device.user_id == user_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()


async def _run() -> None:
    try:
        if not await _database_available():
            if os.getenv("CI"):
                raise AssertionError("CI 必须提供可访问的真实测试数据库")
            pytest.skip("本机测试数据库不可达")
        await init_db()
        await _migrate_add_columns()
        await _exercise_single_device_policy()
    finally:
        await engine.dispose()


def test_single_device_login_pat_and_deployment_isolation() -> None:
    asyncio.run(_run())
