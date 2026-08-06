"""add display version numbers to skill_versions

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-08-05 11:25:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a7b8c9d0e1f2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "skill_versions",
        sa.Column("version_number", sa.String(length=32), nullable=True),
    )
    # 存量整数序列 v1/v2… 统一映射为展示版本 v1.1/v1.2…。
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "UPDATE skill_versions "
            "SET version_number = CONCAT('1.', seq) "
            "WHERE version_number IS NULL"
        )
    else:
        op.execute(
            "UPDATE skill_versions "
            "SET version_number = '1.' || CAST(seq AS VARCHAR) "
            "WHERE version_number IS NULL"
        )
    op.alter_column(
        "skill_versions",
        "version_number",
        existing_type=sa.String(length=32),
        nullable=False,
    )
    op.create_unique_constraint(
        "uq_skill_versions_skill_version_number",
        "skill_versions",
        ["skill_id", "version_number"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_skill_versions_skill_version_number",
        "skill_versions",
        type_="unique",
    )
    op.drop_column("skill_versions", "version_number")
