"""Разборы команд текстом (AiCommand)

Revision ID: 0009_ai_commands
Revises: 0008_workouts
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_ai_commands"
down_revision = "0008_workouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("ai_command",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("day", sa.Date(), nullable=False),
    sa.Column("mode", sa.String(length=8), nullable=False),
    sa.Column("text", sa.Text(), nullable=False),
    sa.Column("actions", sa.JSON(), nullable=False),
    sa.Column("undo", sa.JSON(), nullable=False),
    sa.Column("status", sa.String(length=10), nullable=False),
    sa.Column("tokens_in", sa.Integer(), nullable=False),
    sa.Column("tokens_out", sa.Integer(), nullable=False),
    sa.Column("cost_usd", sa.Float(), nullable=False),
    sa.Column("done_at", sa.DateTime(), nullable=True),
    sa.Column("public_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_ai_command_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_ai_command")),
    sa.UniqueConstraint("public_id", name=op.f("uq_ai_command_public_id"))
    )
    with op.batch_alter_table("ai_command", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_ai_command_user_id"), ["user_id"], unique=False)



def downgrade() -> None:
    with op.batch_alter_table("ai_command", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_ai_command_user_id"))

    op.drop_table("ai_command")
