import logging
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Response,
    UploadFile,
)
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.schemas.auth import (
    ApiKeyStatusResponse,
    CaptchaChallengeResponse,
    CaptchaVerifyRequest,
    CaptchaVerifyResponse,
    GenerateApiKeyResponse,
    LoginRequest,
    LogoutResponse,
    OnboardingRequest,
    OnboardingResponse,
    ProfileUpdateRequest,
    RegisterRequest,
    TokenResponse,
    UserInfo,
    UserResponse,
)
from app.services import auth_service, avatar_service, captcha_service

logger = logging.getLogger(__name__)

api_router = APIRouter(prefix="/auth", tags=["auth"])
_AVATAR_CACHE_CONTROL = "public, max-age=3600, stale-while-revalidate=86400"


def _check_captcha(captcha_token: str) -> Optional[dict]:
    """CAPTCHA_REQUIRED 开启时校验并消费滑块验证 token；失败返回错误响应。"""
    if not settings.CAPTCHA_REQUIRED:
        return None
    if not captcha_service.consume_token(captcha_token):
        return {"success": False, "error": "请先完成滑块验证"}
    return None


async def get_current_credential(
    authorization: Optional[str] = Header(None),
) -> auth_service.AuthCredential:
    """从 Authorization header 提取并校验凭据及设备上下文。

    统一凭据路径：登录态（vhs_）与长期 API Key（vhk_）同走 verify_credential。
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="未提供认证信息")

    token = authorization
    if token.startswith("Bearer "):
        token = token[7:]
    token = token.strip()

    credential = await auth_service.verify_credential_info(token)
    if not credential:
        reason = await auth_service.credential_failure_reason(token)
        detail = (
            "账号已在另一台设备登录"
            if reason == "signed_in_elsewhere"
            else "无效或过期的凭据"
        )
        raise HTTPException(status_code=401, detail=detail)
    return credential


async def get_current_user_id(
    credential: auth_service.AuthCredential = Depends(get_current_credential),
) -> str:
    return credential.user_id


def _versioned_avatar_url(user) -> Optional[str]:
    if not user.avatar_url:
        return None
    updated_at = getattr(user, "updated_at", None)
    if not updated_at:
        return user.avatar_url
    version = updated_at.strftime("%Y%m%d%H%M%S%f")
    separator = "&" if "?" in user.avatar_url else "?"
    return f"{user.avatar_url}{separator}updated_at={version}"


def _to_user_info(user) -> UserInfo:
    return UserInfo(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        avatar_url=_versioned_avatar_url(user),
        phone=getattr(user, "phone", None),
        gender=getattr(user, "gender", None),
        birthday=getattr(user, "birthday", None),
        locale=getattr(user, "locale", None),
        location=getattr(user, "location", None),
        created_at=user.created_at.isoformat() if user.created_at else None,
        onboarded=bool(user.onboarded),
        dev_mode=user.dev_mode,
        favorite_tool=user.favorite_tool,
        is_platform_admin=bool(getattr(user, "is_platform_admin", False)),
        is_seed_user=auth_service.is_seed_user(user),
        is_reviewer=auth_service.is_reviewer(user),
        can_manage_admins=auth_service.can_manage_admins(user),
    )


async def _read_limited_upload(file: UploadFile) -> bytes:
    chunks = []
    size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > avatar_service.MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="头像文件不能超过 5MiB")
        chunks.append(chunk)
    return b"".join(chunks)


def _etag_matches(if_none_match: Optional[str], etag: str) -> bool:
    if not if_none_match:
        return False
    tags = {item.strip() for item in if_none_match.split(",")}
    return "*" in tags or etag in tags or f"W/{etag}" in tags


@api_router.get("/captcha", response_model=CaptchaChallengeResponse)
async def get_captcha():
    try:
        challenge = captcha_service.create_challenge()
        return {"success": True, **challenge}
    except Exception as e:
        logger.exception("[auth/captcha] 生成滑块挑战失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/captcha/verify", response_model=CaptchaVerifyResponse)
async def verify_captcha(data: CaptchaVerifyRequest):
    token = captcha_service.verify(data.captcha_id, data.x)
    if not token:
        return {"success": False, "error": "验证未通过，请重试"}
    return {"success": True, "captcha_token": token}


@api_router.post("/register", response_model=TokenResponse)
async def register(data: RegisterRequest):
    captcha_error = _check_captcha(data.captcha_token)
    if captcha_error:
        return captcha_error
    try:
        result = await auth_service.register(
            username=data.username,
            password=data.password,
            display_name=data.display_name,
            email=data.email,
            invite_code=data.invite_code,
            client_uuid=data.client_uuid,
            platform=data.platform,
            hostname=data.hostname,
            app_version=data.app_version,
            agent_version=data.agent_version,
        )
        return result
    except Exception as e:
        logger.exception("[auth/register] 注册失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest):
    captcha_error = _check_captcha(data.captcha_token)
    if captcha_error:
        return captcha_error
    try:
        result = await auth_service.login(
            data.username,
            data.password,
            data.client_uuid,
            platform=data.platform,
            hostname=data.hostname,
            app_version=data.app_version,
            agent_version=data.agent_version,
        )
        return result
    except Exception as e:
        logger.exception("[auth/login] 登录失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.get("/me", response_model=UserResponse)
async def get_me(
    credential: auth_service.AuthCredential = Depends(get_current_credential),
):
    user = await auth_service.get_user_by_id(credential.user_id)
    if not user:
        return {"success": False, "error": "用户不存在"}
    return {
        "success": True,
        "user": _to_user_info(user),
        "credential": {
            "kind": credential.kind,
            "device_id": credential.device_id,
        },
    }


@api_router.patch("/me", response_model=UserResponse)
async def update_me(
    data: ProfileUpdateRequest,
    user_id: str = Depends(get_current_user_id),
):
    result = await auth_service.update_profile(
        user_id, data.model_dump(exclude_unset=True)
    )
    if not result.get("success"):
        status_code = 409 if "邮箱" in result.get("error", "") else 404
        raise HTTPException(status_code=status_code, detail=result["error"])
    return {"success": True, "user": _to_user_info(result["user"])}


@api_router.post("/me/avatar", response_model=UserResponse)
async def upload_my_avatar(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user_id),
):
    content_type = (file.content_type or "").split(";", 1)[0].lower()
    if content_type not in avatar_service.ALLOWED_CONTENT_TYPES:
        await file.close()
        raise HTTPException(
            status_code=415, detail="仅支持 JPEG、PNG 或 WebP 图片"
        )
    try:
        raw = await _read_limited_upload(file)
    finally:
        await file.close()

    try:
        await run_in_threadpool(
            avatar_service.save_avatar, user_id, raw, content_type
        )
    except avatar_service.AvatarValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    avatar_url = f"/api/v1/auth/users/{user_id}/avatar"
    result = await auth_service.set_avatar_url(user_id, avatar_url)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result["error"])
    return {"success": True, "user": _to_user_info(result["user"])}


@api_router.delete("/me/avatar", response_model=UserResponse)
async def delete_my_avatar(user_id: str = Depends(get_current_user_id)):
    await run_in_threadpool(avatar_service.delete_avatar, user_id)
    result = await auth_service.set_avatar_url(user_id, None)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result["error"])
    return {"success": True, "user": _to_user_info(result["user"])}


@api_router.get("/users/{user_id}/avatar")
async def get_user_avatar(
    user_id: str,
    if_none_match: Optional[str] = Header(None, alias="If-None-Match"),
):
    try:
        data = await run_in_threadpool(avatar_service.get_avatar, user_id)
    except ValueError:
        data = None
    if data is None:
        raise HTTPException(status_code=404, detail="头像不存在")

    etag = avatar_service.avatar_etag(data)
    headers = {
        "ETag": etag,
        "Cache-Control": _AVATAR_CACHE_CONTROL,
    }
    if _etag_matches(if_none_match, etag):
        return Response(status_code=304, headers=headers)
    return Response(content=data, media_type="image/webp", headers=headers)


@api_router.post("/onboarding", response_model=OnboardingResponse)
async def save_onboarding(
    data: OnboardingRequest,
    user_id: str = Depends(get_current_user_id),
):
    try:
        return await auth_service.save_onboarding(
            user_id, data.dev_mode, data.favorite_tool
        )
    except Exception as e:
        logger.exception("[auth/onboarding] 保存引导选择失败")
        raise HTTPException(status_code=500, detail=str(e))


@api_router.post("/api-key", response_model=GenerateApiKeyResponse)
async def generate_api_key(
    credential: auth_service.AuthCredential = Depends(get_current_credential),
):
    if credential.kind != "session":
        raise HTTPException(status_code=403, detail="仅桌面登录会话可以签发 CLI Key")
    return await auth_service.generate_api_key(
        credential.user_id, credential.device_id
    )


@api_router.get("/api-key/status", response_model=ApiKeyStatusResponse)
async def get_api_key_status(
    credential: auth_service.AuthCredential = Depends(get_current_credential),
):
    return {
        "success": True,
        "has_api_key": await auth_service.has_active_api_key(
            credential.user_id, credential.device_id
        ),
    }


@api_router.post("/logout", response_model=LogoutResponse)
async def logout(
    credential: auth_service.AuthCredential = Depends(get_current_credential),
):
    await auth_service.revoke_credential(credential.token_id, "logout")
    from app.websocket.hub import close_user_connections

    await close_user_connections(credential.user_id, code=1000, reason="logout")
    return {"success": True}
