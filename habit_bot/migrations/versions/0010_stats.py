"""Последняя выбранная привычка в «Итогах» (StatsSettings)

Revision ID: 0010_stats
Revises: 0009_ai_commands
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_stats"
down_revision = "0009_ai_commands"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("stats_settings",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("section", sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_stats_settings_user_id_users"),
                            ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_stats_settings")),
    sa.UniqueConstraint("user_id", name="uq_stats_settings_user_id")
    )


def downgrade() -> None:
    op.drop_table("stats_settings")
