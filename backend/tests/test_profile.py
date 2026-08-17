"""个人资料与头像功能测试。"""

import asyncio
import io
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import auth as auth_api  # noqa: E402
from app.schemas.auth import ProfileUpdateRequest  # noqa: E402
from app.services import auth_service, avatar_service  # noqa: E402
from app.services.object_store import LocalObjectStore  # noqa: E402


def _image_bytes(
    image_format: str = "PNG",
    size: tuple[int, int] = (800, 400),
    color: str = "red",
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format=image_format)
    return output.getvalue()


def test_profile_schema_partial_update_and_clear_semantics():
    assert ProfileUpdateRequest().model_dump(exclude_unset=True) == {}

    parsed = ProfileUpdateRequest(
        display_name="  测试用户  ",
        email="  USER@Example.COM ",
        phone=" 13800138000 ",
        gender="OTHER",
        birthday="2000-01-02",
        locale=" zh-CN ",
        location=" 上海 ",
    )
    assert parsed.display_name == "测试用户"
    assert parsed.email == "user@example.com"
    assert parsed.phone == "13800138000"
    assert parsed.gender == "other"
    assert parsed.birthday == date(2000, 1, 2)
    assert parsed.locale == "zh-CN"
    assert parsed.location == "上海"

    cleared = ProfileUpdateRequest(
        email="", phone="", gender="", birthday=None, locale="", location=""
    )
    assert cleared.model_dump() == {
        "display_name": None,
        "email": None,
        "phone": None,
        "gender": None,
        "birthday": None,
        "locale": None,
        "location": None,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"display_name": ""},
        {"display_name": None},
        {"display_name": "x" * 129},
        {"email": "not-an-email"},
        {"gender": "unknown"},
        {"phone": "1" * 33},
        {"locale": "x" * 17},
        {"location": "x" * 257},
        {"birthday": date.today() + timedelta(days=1)},
    ],
)
def test_profile_schema_rejects_invalid_values(payload):
    with pytest.raises(ValidationError):
        ProfileUpdateRequest(**payload)


def test_profile_routes_use_authentication_gate():
    protected = {
        ("/auth/me", "PATCH"),
        ("/auth/me/avatar", "POST"),
        ("/auth/me/avatar", "DELETE"),
    }
    wired = set()
    for route in auth_api.api_router.routes:
        for method in route.methods or set():
            key = (route.path, method)
            if key in protected:
                assert any(
                    dep.call is auth_api.get_current_user_id
                    for dep in route.dependant.dependencies
                )
                wired.add(key)
    assert wired == protected


def test_authentication_gate_accepts_valid_and_rejects_invalid():
    saved = auth_service.verify_credential

    async def fake_verify(raw):
        return "user-1" if raw == "good" else None

    auth_service.verify_credential = fake_verify
    try:
        assert asyncio.run(auth_api.get_current_user_id("Bearer good")) == "user-1"
        with pytest.raises(HTTPException) as invalid:
            asyncio.run(auth_api.get_current_user_id("Bearer bad"))
        assert invalid.value.status_code == 401
        with pytest.raises(HTTPException) as missing:
            asyncio.run(auth_api.get_current_user_id(None))
        assert missing.value.status_code == 401
    finally:
        auth_service.verify_credential = saved


def test_avatar_processing_outputs_square_webp():
    result = avatar_service.process_avatar(_image_bytes(), "image/png")
    with Image.open(io.BytesIO(result)) as image:
        assert image.format == "WEBP"
        assert image.size == (512, 512)


def test_avatar_processing_applies_exif_orientation():
    source = Image.new("RGB", (200, 400), "red")
    source.paste("blue", (0, 200, 200, 400))
    exif = source.getexif()
    exif[274] = 6  # 顺时针旋转 90 度
    raw = io.BytesIO()
    source.save(raw, format="JPEG", quality=100, exif=exif)

    result = avatar_service.process_avatar(raw.getvalue(), "image/jpeg")
    with Image.open(io.BytesIO(result)) as image:
        left = image.getpixel((64, 256))
        right = image.getpixel((448, 256))
        assert left[2] > left[0]
        assert right[0] > right[2]


def test_avatar_processing_rejects_unsafe_inputs(monkeypatch):
    with pytest.raises(avatar_service.AvatarValidationError):
        avatar_service.process_avatar(b"not-an-image", "image/png")
    with pytest.raises(avatar_service.AvatarValidationError):
        avatar_service.process_avatar(_image_bytes(), "image/gif")
    with pytest.raises(avatar_service.AvatarValidationError):
        avatar_service.process_avatar(
            b"x" * (avatar_service.MAX_UPLOAD_BYTES + 1), "image/png"
        )

    monkeypatch.setattr(avatar_service, "MAX_IMAGE_PIXELS", 100)
    with pytest.raises(avatar_service.AvatarValidationError, match="像素"):
        avatar_service.process_avatar(
            _image_bytes(size=(20, 20)), "image/png"
        )


def test_avatar_local_store_replace_read_and_delete(tmp_path):
    store = LocalObjectStore(str(tmp_path))
    first = avatar_service.save_avatar(
        "user-1", _image_bytes(color="red"), "image/png", store=store
    )
    second = avatar_service.save_avatar(
        "user-1", _image_bytes(color="blue"), "image/png", store=store
    )

    assert first != second
    assert store.list("avatars/user-1/") == ["avatars/user-1/avatar.webp"]
    assert avatar_service.get_avatar("user-1", store=store) == second

    avatar_service.delete_avatar("user-1", store=store)
    assert avatar_service.get_avatar("user-1", store=store) is None
    assert store.list("avatars/user-1/") == []


def test_public_avatar_response_etag(monkeypatch):
    data = avatar_service.process_avatar(_image_bytes(), "image/png")
    monkeypatch.setattr(avatar_service, "get_avatar", lambda user_id: data)

    response = asyncio.run(auth_api.get_user_avatar("user-1", None))
    assert response.status_code == 200
    assert response.media_type == "image/webp"
    assert response.body == data
    assert response.headers["etag"] == avatar_service.avatar_etag(data)
    assert response.headers["cache-control"].startswith("public")

    cached = asyncio.run(
        auth_api.get_user_avatar("user-1", response.headers["etag"])
    )
    assert cached.status_code == 304
    assert cached.body == b""


def test_user_info_uses_versioned_relative_avatar_url():
    user = SimpleNamespace(
        id="user-1",
        username="tester",
        display_name="Tester",
        email=None,
        avatar_url="/api/v1/auth/users/user-1/avatar",
        phone=None,
        gender=None,
        birthday=None,
        locale=None,
        location=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 2, 3, 4, 5, 6000),
        onboarded=False,
        dev_mode=None,
        favorite_tool=None,
        is_platform_admin=False,
    )
    info = auth_api._to_user_info(user)
    assert info.avatar_url == (
        "/api/v1/auth/users/user-1/avatar?updated_at=20260102030405006000"
    )


async def _profile_db_roundtrip() -> str:
    from sqlalchemy import delete, text

    from app.core.database import async_session_factory, engine
    from app.models.user import User

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        await engine.dispose()
        return "skip"

    suffix = uuid.uuid4().hex[:10]
    first = User(
        username=f"profile-a-{suffix}",
        display_name="Profile A",
        password_hash="test-only",
    )
    second = User(
        username=f"profile-b-{suffix}",
        display_name="Profile B",
        password_hash="test-only",
    )
    async with async_session_factory() as session:
        session.add_all([first, second])
        await session.commit()
        first_id, second_id = first.id, second.id

    try:
        email = f"{suffix}@example.com"
        updated = await auth_service.update_profile(
            first_id,
            {
                "display_name": "Updated",
                "email": email,
                "phone": "13800138000",
                "gender": "other",
                "birthday": date(2000, 1, 2),
                "locale": "zh-CN",
                "location": "上海",
            },
        )
        assert updated["success"], updated
        assert updated["user"].display_name == "Updated"
        assert updated["user"].email == email
        assert updated["user"].birthday == date(2000, 1, 2)

        conflict = await auth_service.update_profile(second_id, {"email": email})
        assert conflict == {
            "success": False,
            "error": "该邮箱已被其他账号使用",
        }

        cleared = await auth_service.update_profile(
            first_id, {"email": None, "phone": None, "birthday": None}
        )
        assert cleared["success"], cleared
        assert cleared["user"].email is None
        assert cleared["user"].phone is None
        assert cleared["user"].birthday is None
        return "ok"
    finally:
        async with async_session_factory() as session:
            await session.execute(
                delete(User).where(User.id.in_([first_id, second_id]))
            )
            await session.commit()
        await engine.dispose()


def test_profile_service_db_roundtrip():
    if asyncio.run(_profile_db_roundtrip()) == "skip":
        pytest.skip("MySQL 不可达")
