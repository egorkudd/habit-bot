"""Цель привычки за день, неделю или месяц (Habit.period, правки 1.0.2)

Revision ID: 0016_habit_period
Revises: 0015_stats_nutrients
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_habit_period"
down_revision = "0015_stats_nutrients"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("habits_habit") as batch_op:
        batch_op.add_column(sa.Column("period", sa.String(length=8), server_default="day", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("habits_habit") as batch_op:
        batch_op.drop_column("period")
