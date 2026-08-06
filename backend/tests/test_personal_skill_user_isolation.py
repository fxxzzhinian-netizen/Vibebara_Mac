import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import UniqueConstraint

from app.models.skill_package import PersonalSkill
from app.services import native_skill_store as store_module
from app.services.native_skill_store import NativeSkillStore
from app.services.object_store import LocalObjectStore


class _LookupSession:
    def __init__(self, existing_id: str | None = None):
        self.existing_id = existing_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scalar(self, _statement):
        return self.existing_id


def _personal_row(
    skill_id: str,
    name: str,
    owner_id: str,
    store_path: str,
) -> PersonalSkill:
    now = datetime.now(timezone.utc)
    return PersonalSkill(
        id=skill_id,
        name=name,
        owner_id=owner_id,
        display_name="",
        description="",
        short_description="",
        version="1.0.0",
        tags=[],
        imported_from="manual",
        store_path=store_path,
        content_hash="",
        deployed_cursor=False,
        deployed_codex=False,
        deployed_windsurf=False,
        deployed_claude=False,
        deployed_kiro=False,
        deployed_trae=False,
        deployed_qoder=False,
        deployed_workbuddy=False,
        created_at=now,
        updated_at=now,
    )


def test_two_users_can_create_same_personal_skill_name(tmp_path, monkeypatch):
    object_store = LocalObjectStore(str(tmp_path / "store"))
    monkeypatch.setattr(
        NativeSkillStore,
        "_store",
        classmethod(lambda cls: object_store),
    )
    monkeypatch.setattr(
        store_module,
        "async_session_factory",
        lambda: _LookupSession(),
    )

    async def fake_upsert(
        cls,
        skill_id,
        config,
        store_path,
        *,
        owner_id=None,
        name=None,
        **_kwargs,
    ):
        return _personal_row(skill_id, name or config["name"], owner_id, store_path)

    async def ignore_event(**_kwargs):
        return None

    monkeypatch.setattr(
        NativeSkillStore,
        "_upsert_db",
        classmethod(fake_upsert),
    )
    monkeypatch.setattr(
        store_module.SkillSyncService,
        "on_skill_changed",
        ignore_event,
    )

    async def scenario():
        first = await NativeSkillStore.create(
            {"name": "develop-sop", "description": "A"},
            owner_id="user-a",
        )
        second = await NativeSkillStore.create(
            {"name": "develop-sop", "description": "B"},
            owner_id="user-b",
        )

        assert first["name"] == second["name"] == "develop-sop"
        assert first["id"] != second["id"]
        uuid.UUID(first["id"])
        uuid.UUID(second["id"])
        assert first["store_path"] == f"skills/personal/user-a/{first['id']}"
        assert second["store_path"] == f"skills/personal/user-b/{second['id']}"
        assert object_store.exists(first["store_path"] + "/skill.config.yaml")
        assert object_store.exists(second["store_path"] + "/skill.config.yaml")

    asyncio.run(scenario())


def test_same_user_duplicate_name_is_rejected_before_cos_write(tmp_path, monkeypatch):
    object_store = LocalObjectStore(str(tmp_path / "store"))
    monkeypatch.setattr(
        NativeSkillStore,
        "_store",
        classmethod(lambda cls: object_store),
    )
    monkeypatch.setattr(
        store_module,
        "async_session_factory",
        lambda: _LookupSession("existing-id"),
    )

    async def scenario():
        with pytest.raises(ValueError, match="already exists"):
            await NativeSkillStore.create(
                {"name": "develop-sop", "description": "duplicate"},
                owner_id="user-a",
            )
        assert object_store.list("skills/personal") == []

    asyncio.run(scenario())


def test_personal_prefix_requires_owner_and_uses_internal_id():
    with pytest.raises(ValueError, match="owner_id"):
        NativeSkillStore._personal_prefix("", "skill-id")
    assert (
        NativeSkillStore._personal_prefix("user-a", "skill-id")
        == "skills/personal/user-a/skill-id"
    )


def test_personal_name_uniqueness_is_scoped_to_owner():
    constraints = [
        constraint
        for constraint in PersonalSkill.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    ]
    assert any(
        constraint.name == "uq_personal_skill_owner_name"
        and [column.name for column in constraint.columns] == ["owner_id", "name"]
        for constraint in constraints
    )


def test_personal_skill_access_is_owner_only():
    row = _personal_row(
        "skill-id",
        "develop-sop",
        "user-a",
        "skills/personal/user-a/skill-id",
    )
    session = _LookupSession()

    async def scenario():
        assert await NativeSkillStore._row_accessible(session, row, "user-a")
        assert not await NativeSkillStore._row_accessible(session, row, "user-b")

    asyncio.run(scenario())


def test_startup_sync_does_not_prune_db_when_object_listing_fails(monkeypatch):
    class _FailingStore:
        def list_dirs(self, _prefix):
            raise RuntimeError("temporary COS failure")

    class _PruneSession:
        def __init__(self):
            self.executed = []

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, statement):
            self.executed.append(statement)

        async def commit(self):
            return None

    session = _PruneSession()
    monkeypatch.setattr(
        NativeSkillStore,
        "_store",
        classmethod(lambda cls: _FailingStore()),
    )
    monkeypatch.setattr(
        store_module,
        "async_session_factory",
        lambda: session,
    )

    asyncio.run(NativeSkillStore._sync_from_filesystem())
    assert session.executed == []
