"""bind credentials and deployments to a single active device

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-08-18 14:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0e1f2a3b4c5"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "auth_tokens",
        sa.Column("device_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "auth_tokens",
        sa.Column(
            "revoked_reason",
            sa.String(length=64),
            nullable=False,
            server_default="",
        ),
    )
    op.create_index("ix_auth_tokens_device_id", "auth_tokens", ["device_id"])
    op.create_foreign_key(
        "fk_auth_tokens_user_id",
        "auth_tokens",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_auth_tokens_device_id",
        "auth_tokens",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.add_column(
        "user_skill_deployments",
        sa.Column("device_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_user_skill_deployments_device_id",
        "user_skill_deployments",
        ["device_id"],
    )
    op.create_foreign_key(
        "fk_user_skill_deployments_device_id",
        "user_skill_deployments",
        "devices",
        ["device_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # deploy_path 使用前缀索引，避免 utf8mb4 下超过 MySQL 3072-byte 索引上限。
    op.execute(
        "CREATE UNIQUE INDEX uq_usr_dev_proj_skill_tool_path "
        "ON user_skill_deployments "
        "(user_id, device_id, project_id, team_skill_id, tool_type, deploy_path(191))"
    )

    # 旧凭据不带设备归属，升级后强制重新登录，避免绕过单设备策略。
    op.execute(
        "UPDATE auth_tokens "
        "SET revoked_reason = CASE WHEN revoked_at IS NULL "
        "THEN 'single_device_migration' ELSE revoked_reason END, "
        "revoked_at = COALESCE(revoked_at, NOW())"
    )


def downgrade() -> None:
    op.drop_index(
        "uq_usr_dev_proj_skill_tool_path",
        table_name="user_skill_deployments",
    )
    op.drop_constraint(
        "fk_user_skill_deployments_device_id",
        "user_skill_deployments",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_user_skill_deployments_device_id",
        table_name="user_skill_deployments",
    )
    op.drop_column("user_skill_deployments", "device_id")

    op.drop_constraint("fk_auth_tokens_device_id", "auth_tokens", type_="foreignkey")
    op.drop_constraint("fk_auth_tokens_user_id", "auth_tokens", type_="foreignkey")
    op.drop_index("ix_auth_tokens_device_id", table_name="auth_tokens")
    op.drop_column("auth_tokens", "revoked_reason")
    op.drop_column("auth_tokens", "device_id")
