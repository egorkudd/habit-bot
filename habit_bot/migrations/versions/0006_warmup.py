"""Зарядка: набор, зарядки и упражнения в них, личные цели, цель «зарядок в день»

Revision ID: 0006_warmup
Revises: 0005_food
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_warmup"
down_revision = "0005_food"
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
        "warmup_template",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("short", sa.String(length=24), nullable=False),
        sa.Column("measure", sa.String(length=8), nullable=False),
        sa.Column("step", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_common(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warmup_template_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warmup_template")),
        sa.UniqueConstraint("public_id", name=op.f("uq_warmup_template_public_id")),
    )
    op.create_index(op.f("ix_warmup_template_user_id"), "warmup_template", ["user_id"], unique=False)
    op.create_table(
        "warmup_session",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("logged_at", sa.DateTime(), nullable=False),
        *_common(),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warmup_session_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warmup_session")),
        sa.UniqueConstraint("public_id", name=op.f("uq_warmup_session_public_id")),
    )
    op.create_index(op.f("ix_warmup_session_day"), "warmup_session", ["day"], unique=False)
    op.create_table(
        "warmup_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("measure", sa.String(length=8), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["warmup_session.id"],
                                name=op.f("fk_warmup_item_session_id_warmup_session"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["warmup_template.id"],
                                name=op.f("fk_warmup_item_template_id_warmup_template"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warmup_item_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warmup_item")),
    )
    op.create_index(op.f("ix_warmup_item_session_id"), "warmup_item", ["session_id"], unique=False)
    op.create_table(
        "warmup_goal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("target", sa.Integer(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("start_value", sa.Integer(), nullable=False),
        sa.Column("set_on", sa.Date(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *_common(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["warmup_template.id"],
                                name=op.f("fk_warmup_goal_template_id_warmup_template"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warmup_goal_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warmup_goal")),
        sa.UniqueConstraint("public_id", name=op.f("uq_warmup_goal_public_id")),
    )
    op.create_table(
        "warmup_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("daily_goal", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_warmup_settings_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_warmup_settings")),
        sa.UniqueConstraint("user_id", name="uq_warmup_settings_user_id"),
    )


def downgrade() -> None:
    op.drop_table("warmup_settings")
    op.drop_table("warmup_goal")
    op.drop_index(op.f("ix_warmup_item_session_id"), table_name="warmup_item")
    op.drop_table("warmup_item")
    op.drop_index(op.f("ix_warmup_session_day"), table_name="warmup_session")
    op.drop_table("warmup_session")
    op.drop_index(op.f("ix_warmup_template_user_id"), table_name="warmup_template")
    op.drop_table("warmup_template")
