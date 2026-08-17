"""add project permission policies

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-08-11 10:37:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b8c9d0e1f2a3"
down_revision: Union[str, None] = "a7b8c9d0e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "project_permission_policies",
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("member_permissions", sa.JSON(), nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name="fk_project_permission_policies_project_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by"],
            ["users.id"],
            name="fk_project_permission_policies_updated_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "project_id",
            name="pk_project_permission_policies",
        ),
    )
    op.create_index(
        "ix_project_permission_policies_updated_by",
        "project_permission_policies",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_project_permission_policies_updated_by",
        table_name="project_permission_policies",
    )
    op.drop_table("project_permission_policies")
