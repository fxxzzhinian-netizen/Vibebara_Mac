"""团队 Skill 展示版本号规则单测（无需真实数据库）。"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.skill_version_service import SkillVersionService  # noqa: E402


class _ScalarRows:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return _ScalarRows(self._row)


class _FakeSession:
    def __init__(self, latest=None, existing=None):
        self.latest = latest
        self.existing = existing

    async def execute(self, _statement):
        return _Result(self.latest)

    async def scalar(self, _statement):
        if isinstance(self.existing, list):
            return self.existing.pop(0) if self.existing else None
        return self.existing


def test_version_number_validation():
    assert SkillVersionService.validate_version_number("1.1") == "1.1"
    assert SkillVersionService.validate_version_number(" 2.10 ") == "2.10"
    for invalid in ("", "1", "1.2.3", "v1.2", "1.02", "a.b"):
        try:
            SkillVersionService.validate_version_number(invalid)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝非法版本号: {invalid!r}")


def test_minor_increment_is_not_float_math():
    assert SkillVersionService.increment_version_number("1.1") == "1.2"
    assert SkillVersionService.increment_version_number("1.9") == "1.10"
    assert SkillVersionService.increment_version_number("2.99") == "2.100"


def test_default_version_number_and_legacy_mapping():
    assert asyncio.run(
        SkillVersionService._next_version_number(_FakeSession(), "skill-a")
    ) == "1.1"
    legacy = SimpleNamespace(seq=9, version_number="")
    assert asyncio.run(
        SkillVersionService._next_version_number(
            _FakeSession(latest=legacy),
            "skill-a",
        )
    ) == "1.10"


def test_manual_version_and_duplicate_guard():
    resolved = asyncio.run(
        SkillVersionService._resolve_version_number(
            _FakeSession(existing=None),
            "skill-a",
            "2.5",
        )
    )
    assert resolved == "2.5"

    try:
        asyncio.run(
            SkillVersionService._resolve_version_number(
                _FakeSession(existing="version-id"),
                "skill-a",
                "2.5",
            )
        )
    except ValueError as exc:
        assert "已存在" in str(exc)
    else:
        raise AssertionError("重复版本号应被拒绝")


def test_automatic_version_skips_existing_number():
    latest = SimpleNamespace(seq=10, version_number="1.9")
    resolved = asyncio.run(
        SkillVersionService._resolve_version_number(
            _FakeSession(latest=latest, existing=["version-1.10", None]),
            "skill-a",
            "",
        )
    )
    assert resolved == "1.11"


def _run_all():
    tests = [
        test_version_number_validation,
        test_minor_increment_is_not_float_math,
        test_default_version_number_and_legacy_mapping,
        test_manual_version_and_duplicate_guard,
        test_automatic_version_skips_existing_number,
    ]
    for test in tests:
        test()
        print(f"  PASS  {test.__name__}")
    print(f"\nAll {len(tests)} skill-version-number tests passed.")


if __name__ == "__main__":
    _run_all()
