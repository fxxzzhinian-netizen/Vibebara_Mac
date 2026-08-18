import re
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    username: str
    password: str
    display_name: str = ""
    email: Optional[str] = None
    # 注册邀请码（INVITE_CODE_REQUIRED 开启时必填），格式 VH-XXXX-XXXX
    invite_code: str = ""
    # 滑块验证 token（CAPTCHA_REQUIRED 开启时必填）
    captcha_token: str = ""
    client_uuid: str = Field(min_length=1, max_length=64)
    platform: str = Field(default="", max_length=16)
    hostname: Optional[str] = Field(default=None, max_length=128)
    app_version: Optional[str] = Field(default=None, max_length=32)
    agent_version: Optional[str] = Field(default=None, max_length=32)


class LoginRequest(BaseModel):
    username: str
    password: str
    # 滑块验证 token（CAPTCHA_REQUIRED 开启时必填）
    captcha_token: str = ""
    client_uuid: str = Field(min_length=1, max_length=64)
    platform: str = Field(default="", max_length=16)
    hostname: Optional[str] = Field(default=None, max_length=128)
    app_version: Optional[str] = Field(default=None, max_length=32)
    agent_version: Optional[str] = Field(default=None, max_length=32)


class TokenResponse(BaseModel):
    success: bool
    token: str = ""
    user_id: str = ""
    username: str = ""
    device_id: str = ""
    error: Optional[str] = None


class LogoutResponse(BaseModel):
    success: bool


class UserInfo(BaseModel):
    id: str
    username: str
    display_name: str
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    phone: Optional[str] = None
    gender: Optional[str] = None
    birthday: Optional[date] = None
    locale: Optional[str] = None
    location: Optional[str] = None
    created_at: Optional[str] = None
    # 首次登录引导状态与选择
    onboarded: bool = False
    dev_mode: Optional[str] = None
    favorite_tool: Optional[str] = None
    # SKILL 市场权限标记（前端据此显示审核 / 管理员入口）
    is_platform_admin: bool = False
    is_seed_user: bool = False
    is_reviewer: bool = False
    can_manage_admins: bool = False


class UserResponse(BaseModel):
    success: bool
    user: Optional[UserInfo] = None
    credential: Optional[dict] = None
    error: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    """个人资料部分更新；未传字段保持不变，空字符串按字段约定清空。"""

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    email: Optional[str] = Field(default=None, max_length=256)
    phone: Optional[str] = Field(default=None, max_length=32)
    gender: Optional[Literal["male", "female", "other", "unspecified"]] = None
    birthday: Optional[date] = None
    locale: Optional[str] = Field(default=None, max_length=16)
    location: Optional[str] = Field(default=None, max_length=256)

    @field_validator("display_name", mode="before")
    @classmethod
    def validate_display_name(cls, value):
        if value is None:
            raise ValueError("display_name 不能为空")
        if not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("display_name 不能为空")
        return value

    @field_validator("email", mode="before")
    @classmethod
    def validate_email(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        value = value.strip().lower()
        if not value:
            return None
        if len(value) > 256 or not _EMAIL_RE.fullmatch(value):
            raise ValueError("邮箱格式不正确")
        return value

    @field_validator("phone", "locale", "location", mode="before")
    @classmethod
    def trim_clearable_text(cls, value):
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        return value.strip() or None

    @field_validator("gender", mode="before")
    @classmethod
    def clear_empty_gender(cls, value):
        if isinstance(value, str):
            return value.strip().lower() or None
        return value

    @field_validator("birthday")
    @classmethod
    def validate_birthday(cls, value):
        if value is not None and value > date.today():
            raise ValueError("生日不能晚于今天")
        return value


class OnboardingRequest(BaseModel):
    # 使用场景偏好：'solo' = 个人独立开发 / 'team' = 团队协同开发
    dev_mode: str
    # 最常用的 Vibe Coding 工具（平台适配 key）
    favorite_tool: str


class OnboardingResponse(BaseModel):
    success: bool
    error: Optional[str] = None


class GenerateApiKeyResponse(BaseModel):
    success: bool
    api_key: str = ""
    error: Optional[str] = None


class ApiKeyStatusResponse(BaseModel):
    success: bool
    has_api_key: bool = False


class CaptchaChallengeResponse(BaseModel):
    success: bool
    captcha_id: str = ""
    bg: str = ""            # base64 PNG（带缺口背景图）
    piece: str = ""         # base64 PNG（透明底拼块）
    piece_y: int = 0
    bg_width: int = 0
    bg_height: int = 0
    piece_width: int = 0
    piece_height: int = 0
    error: Optional[str] = None


class CaptchaVerifyRequest(BaseModel):
    captcha_id: str
    x: float


class CaptchaVerifyResponse(BaseModel):
    success: bool
    captcha_token: str = ""
    error: Optional[str] = None
