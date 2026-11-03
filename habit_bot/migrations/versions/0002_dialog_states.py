"""Незаконченный ввод в Telegram: состояния диалогов (DialogState)

Revision ID: 0002_dialog_states
Revises: 0001_initial
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_dialog_states"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dialog_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("state", sa.String(length=64), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("other_day", sa.Date(), nullable=True),
        sa.Column("token", sa.Integer(), nullable=False),
        sa.Column("last_action_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_dialog_states_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dialog_states")),
        sa.UniqueConstraint("public_id", name=op.f("uq_dialog_states_public_id")),
        sa.UniqueConstraint("user_id", "scope", name="uq_dialog_states_user_id_scope"),
    )
    op.create_index(op.f("ix_dialog_states_last_action_at"), "dialog_states", ["last_action_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dialog_states_last_action_at"), table_name="dialog_states")
    op.drop_table("dialog_states")
