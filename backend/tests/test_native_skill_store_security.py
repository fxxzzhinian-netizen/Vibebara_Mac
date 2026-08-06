import asyncio

import pytest

from app.models.skill_package import PersonalSkill, TeamSkill
from app.services import native_skill_store as store_module
from app.services.native_skill_store import NativeSkillStore
from app.services.object_store import LocalObjectStore


class _FakeSession:
    def __init__(self, row: TeamSkill, member_id: str | None):
        self.row = row
        self.member_id = member_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, model, skill_id):
        if model is PersonalSkill:
            return None
        if model is TeamSkill and skill_id == self.row.id:
            return self.row
        return None

    async def scalar(self, _statement):
        return self.member_id


class _FakeSessionFactory:
    def __init__(self, row: TeamSkill):
        self.row = row
        self.member_id: str | None = None

    def __call__(self):
        return _FakeSession(self.row, self.member_id)


def _team_row(skill_id: str) -> TeamSkill:
    return TeamSkill(
        id=skill_id,
        name="team-demo",
        team_id="team-1",
        source_skill_id=None,
        project_id=None,
        display_name="Team Demo",
        description="",
        short_description="",
        version="1.0.0",
        tags=[],
        imported_from=None,
        store_path=f"skills/team/{skill_id}",
        content_hash="",
        deployed_cursor=False,
        deployed_codex=False,
        deployed_windsurf=False,
        deployed_claude=False,
        deployed_kiro=False,
        deployed_trae=False,
        deployed_qoder=False,
        deployed_workbuddy=False,
    )


def test_team_skill_reads_require_membership(tmp_path, monkeypatch):
    skill_id = "team-demo-team-12345678"
    row = _team_row(skill_id)
    sessions = _FakeSessionFactory(row)
    object_store = LocalObjectStore(str(tmp_path / "store"))
    prefix = f"skills/team/{skill_id}"
    object_store.put_text(prefix + "/skill.config.yaml", "name: team-demo\n")
    object_store.put_text(prefix + "/SKILL.md", "private team content")
    object_store.put_text(prefix + "/references/private.md", "team secret")

    monkeypatch.setattr(store_module, "async_session_factory", sessions)
    monkeypatch.setattr(
        NativeSkillStore,
        "_store",
        classmethod(lambda cls: object_store),
    )

    async def scenario():
        # 任意已登录但非团队成员的用户，不得读取详情或资源内容。
        assert await NativeSkillStore.get_by_id(skill_id, user_id="outsider") is None
        with pytest.raises(PermissionError, match="无权访问"):
            await NativeSkillStore.read_resource_file(
                skill_id,
                "references/private.md",
                user_id="outsider",
            )

        # 同一入口对团队成员正常放行。
        sessions.member_id = "membership-1"
        detail = await NativeSkillStore.get_by_id(skill_id, user_id="member")
        assert detail is not None
        assert detail["vibeh_content"] == "private team content"
        resource = await NativeSkillStore.read_resource_file(
            skill_id,
            "references/private.md",
            user_id="member",
        )
        assert resource["content"] == "team secret"

    asyncio.run(scenario())


def test_ownerless_personal_skill_is_not_public():
    row = PersonalSkill(
        id="ownerless",
        name="ownerless",
        owner_id=None,
        display_name="",
        description="",
        short_description="",
        version="1.0.0",
        tags=[],
        store_path="skills/personal/ownerless",
        content_hash="",
    )
    session = _FakeSession(_team_row("unused-team-skill"), None)

    assert (
        asyncio.run(NativeSkillStore._row_accessible(session, row, "any-user"))
        is False
    )


@pytest.mark.parametrize(
    "bad_key",
    (
        "../outside.txt",
        "skills/../../outside.txt",
        r"..\outside.txt",
        "/absolute/outside.txt",
        "C:/outside.txt",
        "skills//outside.txt",
    ),
)
def test_local_object_store_rejects_escaping_keys(tmp_path, bad_key):
    root = tmp_path / "store"
    outside = tmp_path / "outside.txt"
    object_store = LocalObjectStore(str(root))

    with pytest.raises(ValueError):
        object_store.put_bytes(bad_key, b"escaped")
    with pytest.raises(ValueError):
        object_store.get_bytes(bad_key)
    with pytest.raises(ValueError):
        object_store.list(bad_key)
    with pytest.raises(ValueError):
        object_store.delete_prefix(bad_key)

    assert not outside.exists()
    assert root.exists()


def test_local_object_store_refuses_to_delete_root(tmp_path):
    root = tmp_path / "store"
    object_store = LocalObjectStore(str(root))
    object_store.put_text("skills/personal/demo/SKILL.md", "keep")

    with pytest.raises(ValueError, match="不能为空"):
        object_store.delete_prefix("")

    assert object_store.get_text("skills/personal/demo/SKILL.md") == "keep"
