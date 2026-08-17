"""Focused unit tests for project permission policy primitives."""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api.projects import api_router
from app.api import skill_store
from app.models.project import ProjectPermissionPolicy
from app.models.skill_package import PersonalSkill, TeamSkill
from app.schemas.project import (
    ProjectMemberPermissions,
    ProjectPermissionUpdateRequest,
)
from app.services.project_permission_service import (
    DEFAULT_MEMBER_PERMISSIONS,
    PERMISSION_KEYS,
    normalize_member_permissions,
    resolve_effective_permissions,
)


def _expect_raises(error_type, callback):
    try:
        callback()
    except error_type:
        return
    raise AssertionError(f"Expected {error_type.__name__}")


def test_permission_keys_and_default_policy():
    assert PERMISSION_KEYS == (
        "add_skill",
        "remove_skill",
        "deploy_skill",
        "push_changes",
        "pull_updates",
        "merge_conflicts",
        "manage_tracking",
    )
    assert normalize_member_permissions(None) == DEFAULT_MEMBER_PERMISSIONS
    assert all(DEFAULT_MEMBER_PERMISSIONS.values())


def test_policy_normalization_and_role_resolution():
    configured = DEFAULT_MEMBER_PERMISSIONS | {
        "push_changes": False,
        "merge_conflicts": False,
    }
    assert resolve_effective_permissions("member", configured) == configured
    assert resolve_effective_permissions("admin", configured) == (
        DEFAULT_MEMBER_PERMISSIONS
    )
    assert resolve_effective_permissions("owner", configured) == (
        DEFAULT_MEMBER_PERMISSIONS
    )

    malformed = {"push_changes": False, "add_skill": 1, "unknown": False}
    normalized = normalize_member_permissions(malformed)
    assert normalized["push_changes"] is False
    assert normalized["add_skill"] is True
    assert "unknown" not in normalized


def test_effective_permission_role_matrix():
    restricted = DEFAULT_MEMBER_PERMISSIONS | {
        "add_skill": False,
        "push_changes": False,
    }
    assert resolve_effective_permissions("owner", restricted) == (
        DEFAULT_MEMBER_PERMISSIONS
    )
    assert resolve_effective_permissions("admin", restricted) == (
        DEFAULT_MEMBER_PERMISSIONS
    )
    assert resolve_effective_permissions("member", restricted) == restricted


def test_strict_policy_input_rejects_missing_unknown_and_non_bool():
    _expect_raises(
        ValueError,
        lambda: normalize_member_permissions(
            {"add_skill": True},
            strict=True,
        ),
    )
    _expect_raises(
        ValueError,
        lambda: normalize_member_permissions(
            DEFAULT_MEMBER_PERMISSIONS | {"unknown": True},
            strict=True,
        ),
    )
    _expect_raises(
        ValueError,
        lambda: normalize_member_permissions(
            DEFAULT_MEMBER_PERMISSIONS | {"add_skill": 1},
            strict=True,
        ),
    )


def test_pydantic_permission_schema_is_strict():
    valid = ProjectPermissionUpdateRequest(
        member_permissions=DEFAULT_MEMBER_PERMISSIONS
    )
    assert valid.member_permissions.push_changes is True

    _expect_raises(
        ValidationError,
        lambda: ProjectMemberPermissions.model_validate(
            DEFAULT_MEMBER_PERMISSIONS | {"add_skill": 1}
        ),
    )
    _expect_raises(
        ValidationError,
        lambda: ProjectMemberPermissions.model_validate(
            DEFAULT_MEMBER_PERMISSIONS | {"unknown": True}
        ),
    )


def test_policy_model_and_routes_are_registered():
    table = ProjectPermissionPolicy.__table__
    assert table.name == "project_permission_policies"
    assert table.primary_key.columns.keys() == ["project_id"]
    assert table.c.member_permissions.type.python_type is dict

    route_methods = {
        (route.path, method)
        for route in api_router.routes
        for method in route.methods
    }
    assert ("/projects/{project_id}/permissions", "GET") in route_methods
    assert ("/projects/{project_id}/permissions", "PUT") in route_methods


def test_team_skill_write_role_matrix():
    class FakeSession:
        def __init__(self, *, team_row=None, personal_row=None, role=None):
            self.team_row = team_row
            self.personal_row = personal_row
            self.role = role

        async def get(self, model, _skill_id):
            if model is TeamSkill:
                return self.team_row
            if model is PersonalSkill:
                return self.personal_row
            return None

        async def scalar(self, _query):
            return self.role

    class FakeSessionContext:
        def __init__(self, session):
            self.session = session

        async def __aenter__(self):
            return self.session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    original_factory = skill_store.async_session_factory

    async def assert_allowed(session, user_id="user-1"):
        skill_store.async_session_factory = lambda: FakeSessionContext(session)
        await skill_store._assert_skill_writable("skill-1", user_id)

    async def assert_denied(session, user_id="user-1"):
        skill_store.async_session_factory = lambda: FakeSessionContext(session)
        try:
            await skill_store._assert_skill_writable("skill-1", user_id)
        except PermissionError:
            return
        raise AssertionError("Expected team Skill write to be denied")

    team_row = SimpleNamespace(team_id="team-1")
    personal_row = SimpleNamespace(owner_id="user-1")
    try:
        asyncio.run(assert_allowed(FakeSession(team_row=team_row, role="owner")))
        asyncio.run(assert_allowed(FakeSession(team_row=team_row, role="admin")))
        asyncio.run(assert_denied(FakeSession(team_row=team_row, role="member")))
        asyncio.run(assert_denied(FakeSession(team_row=team_row, role=None)))
        asyncio.run(assert_allowed(FakeSession(personal_row=personal_row)))
        asyncio.run(
            assert_denied(
                FakeSession(personal_row=personal_row),
                user_id="other-user",
            )
        )
    finally:
        skill_store.async_session_factory = original_factory


def _run_all():
    tests = (
        test_permission_keys_and_default_policy,
        test_policy_normalization_and_role_resolution,
        test_effective_permission_role_matrix,
        test_strict_policy_input_rejects_missing_unknown_and_non_bool,
        test_pydantic_permission_schema_is_strict,
        test_policy_model_and_routes_are_registered,
        test_team_skill_write_role_matrix,
    )
    for test in tests:
        test()
        print(f"  PASS  {test.__name__}")
    print(f"\nAll {len(tests)} project-permission tests passed.")


if __name__ == "__main__":
    _run_all()
