import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthToken(Base):
    """统一凭据表：登录态（session）与长期凭据（pat）同表，仅 kind / expires_at 不同。

    单一校验路径（auth_service.verify_credential）：sha256(raw) 命中 token_hash →
    未吊销（revoked_at is None）且未过期（expires_at is None 或 now <= expires_at）→
    返回 user_id。kind/前缀仅作辨识，校验不依赖它。
    """

    __tablename__ = "auth_tokens"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # session / PAT 均绑定签发它的设备；单账号单设备切换时按此列精确吊销。
    device_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("devices.id", ondelete="CASCADE"), nullable=True, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 'session' = 登录态（短期，有 expires_at）；'pat' = 长期无头凭据（默认无过期）
    kind: Mapped[str] = mapped_column(String(16), default="session")
    # PAT 友好名（管理用；列出/命名/单独吊销端点属后续增强）
    name: Mapped[str] = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    # NULL = 永不过期（PAT 默认）；session 为 now + SESSION_TOKEN_TTL
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # NULL = 有效；非空 = 已吊销
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 供客户端区分普通过期与“账号已在另一台设备登录”。
    revoked_reason: Mapped[str] = mapped_column(String(64), default="")
