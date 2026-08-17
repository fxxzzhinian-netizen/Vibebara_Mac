import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(
        String(256), unique=True, nullable=True
    )
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gender: Mapped[str | None] = mapped_column(String(16), nullable=True)
    birthday: Mapped[date | None] = mapped_column(Date, nullable=True)
    locale: Mapped[str | None] = mapped_column(String(16), nullable=True)
    location: Mapped[str | None] = mapped_column(String(256), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(128), default="")
    # 注册时消费的邀请码（规范化形式），用于追溯；种子/历史用户为空
    invite_code_used: Mapped[str | None] = mapped_column(
        String(16), nullable=True
    )
    # 首次登录引导：是否已完成引导流程
    onboarded: Mapped[bool] = mapped_column(Boolean, default=False)
    # 引导问题：使用场景偏好（'solo' = 个人独立开发 / 'team' = 团队协同开发）
    dev_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # 引导问题：最常用的 Vibe Coding 工具（平台适配 key，如 cursor/codex/...）
    favorite_tool: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # 平台管理员：可审核 SKILL 市场发布。由种子用户动态授予（种子用户始终视为管理员）。
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
