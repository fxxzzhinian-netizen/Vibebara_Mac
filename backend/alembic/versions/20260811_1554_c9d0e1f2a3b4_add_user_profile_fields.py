"""add user profile fields

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-08-11 15:54:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b8c9d0e1f2a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("phone", sa.String(length=32), nullable=True))
    op.add_column("users", sa.Column("gender", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("birthday", sa.Date(), nullable=True))
    op.add_column("users", sa.Column("locale", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("location", sa.String(length=256), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "location")
    op.drop_column("users", "locale")
    op.drop_column("users", "birthday")
    op.drop_column("users", "gender")
    op.drop_column("users", "phone")
