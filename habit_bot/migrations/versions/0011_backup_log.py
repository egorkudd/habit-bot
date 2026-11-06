"""Журнал бэкапов (BackupLog)

Revision ID: 0011_backup_log
Revises: 0010_stats
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_backup_log"
down_revision = "0010_stats"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("backup_log",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("ok", sa.Boolean(), nullable=False),
    sa.Column("reason", sa.String(length=16), nullable=False),
    sa.Column("size_kb", sa.Integer(), nullable=False),
    sa.Column("error", sa.String(length=255), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_log"))
    )
    with op.batch_alter_table("backup_log", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_backup_log_created_at"), ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("backup_log", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_backup_log_created_at"))

    op.drop_table("backup_log")
