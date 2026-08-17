"""安全头像处理与对象存储读写。"""

from __future__ import annotations

import hashlib
import io
import re
from typing import Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.object_store import ObjectStore, get_object_store


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 25_000_000
AVATAR_SIZE = 512
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
_SAFE_USER_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class AvatarValidationError(ValueError):
    """头像输入不合法。"""


def _validate_user_id(user_id: str) -> str:
    if not _SAFE_USER_ID_RE.fullmatch(user_id or ""):
        raise ValueError("非法用户 ID")
    return user_id


def avatar_prefix(user_id: str) -> str:
    return f"avatars/{_validate_user_id(user_id)}"


def avatar_key(user_id: str) -> str:
    return f"{avatar_prefix(user_id)}/avatar.webp"


def process_avatar(raw: bytes, content_type: Optional[str] = None) -> bytes:
    """校验原图并输出 512x512 WebP；不信任扩展名或 MIME 类型。"""
    if not raw:
        raise AvatarValidationError("头像文件不能为空")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise AvatarValidationError("头像文件不能超过 5MiB")
    if content_type and content_type.lower() not in ALLOWED_CONTENT_TYPES:
        raise AvatarValidationError("仅支持 JPEG、PNG 或 WebP 图片")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            if (probe.format or "").upper() not in ALLOWED_FORMATS:
                raise AvatarValidationError("仅支持 JPEG、PNG 或 WebP 图片")
            width, height = probe.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise AvatarValidationError("图片像素尺寸过大")
            probe.verify()

        with Image.open(io.BytesIO(raw)) as image:
            image.load()
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA") or (
                image.mode == "P" and "transparency" in image.info
            ):
                image = image.convert("RGBA")
            else:
                image = image.convert("RGB")
            image = ImageOps.fit(
                image,
                (AVATAR_SIZE, AVATAR_SIZE),
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=88, method=6)
            return output.getvalue()
    except AvatarValidationError:
        raise
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError, ValueError):
        raise AvatarValidationError("图片文件无效或已损坏") from None


def save_avatar(
    user_id: str,
    raw: bytes,
    content_type: Optional[str] = None,
    *,
    store: Optional[ObjectStore] = None,
) -> bytes:
    processed = process_avatar(raw, content_type)
    (store or get_object_store()).put_bytes(avatar_key(user_id), processed)
    return processed


def get_avatar(
    user_id: str, *, store: Optional[ObjectStore] = None
) -> Optional[bytes]:
    return (store or get_object_store()).get_bytes(avatar_key(user_id))


def delete_avatar(user_id: str, *, store: Optional[ObjectStore] = None) -> None:
    (store or get_object_store()).delete_prefix(avatar_prefix(user_id))


def avatar_etag(data: bytes) -> str:
    return f'"{hashlib.sha256(data).hexdigest()}"'
