"""Архив встроенных привычек (BuiltinArchive)

Revision ID: 0012_builtin_archive
Revises: 0011_backup_log
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_builtin_archive"
down_revision = "0011_backup_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("habits_builtin_archive",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("key", sa.String(length=16), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_habits_builtin_archive_user_id_users"),
                            ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_habits_builtin_archive")),
    sa.UniqueConstraint("user_id", "key", name="uq_habits_builtin_archive_user_id")
    )


def downgrade() -> None:
    op.drop_table("habits_builtin_archive")
