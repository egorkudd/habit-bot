"""Выходные (DayStatus) и кнопки главного экрана в профиле

Revision ID: 0004_days
Revises: 0003_users_profile
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_days"
down_revision = "0003_users_profile"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "days_status",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_days_status_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_days_status")),
        sa.UniqueConstraint("public_id", name=op.f("uq_days_status_public_id")),
        sa.UniqueConstraint("user_id", "day", name="uq_days_status_user_id_day"),
    )
    with op.batch_alter_table("users_profile") as batch:
        batch.add_column(sa.Column("home_buttons", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users_profile") as batch:
        batch.drop_column("home_buttons")
    op.drop_table("days_status")
