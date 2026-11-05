"""Свои привычки и их записи

Revision ID: 0007_habits
Revises: 0006_warmup
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_habits"
down_revision = "0006_warmup"
branch_labels = None
depends_on = None


def _common() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "habits_habit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("template_key", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("short", sa.String(length=20), nullable=False),
        sa.Column("emoji", sa.String(length=8), nullable=False),
        sa.Column("measure", sa.String(length=8), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("goal", sa.Float(), nullable=True),
        sa.Column("step", sa.Float(), nullable=True),
        sa.Column("quick_values", sa.JSON(), nullable=False),
        sa.Column("weekdays", sa.JSON(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        *_common(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_habits_habit_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habits_habit")),
        sa.UniqueConstraint("public_id", name=op.f("uq_habits_habit_public_id")),
    )
    op.create_index(op.f("ix_habits_habit_user_id"), "habits_habit", ["user_id"], unique=False)
    op.create_table(
        "habits_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("habit_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("logged_at", sa.DateTime(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        *_common(),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["habit_id"], ["habits_habit.id"], name=op.f("fk_habits_entry_habit_id_habits_habit"),
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_habits_entry_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_habits_entry")),
        sa.UniqueConstraint("public_id", name=op.f("uq_habits_entry_public_id")),
    )
    op.create_index(op.f("ix_habits_entry_habit_id"), "habits_entry", ["habit_id"], unique=False)
    op.create_index(op.f("ix_habits_entry_day"), "habits_entry", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_habits_entry_day"), table_name="habits_entry")
    op.drop_index(op.f("ix_habits_entry_habit_id"), table_name="habits_entry")
    op.drop_table("habits_entry")
    op.drop_index(op.f("ix_habits_habit_user_id"), table_name="habits_habit")
    op.drop_table("habits_habit")
