"""Журнал сообщений чата за 48 часов для «🏠 Домой» и ночной чистки (ChatMessage)

Revision ID: 0013_chat_messages
Revises: 0012_builtin_archive
Create Date: 2026-11-06
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_chat_messages"
down_revision = "0012_builtin_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("chat_messages",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("chat_id", sa.BigInteger(), nullable=False),
    sa.Column("message_id", sa.Integer(), nullable=False),
    sa.Column("kept", sa.Boolean(), nullable=False),
    sa.Column("keyboard", sa.Boolean(), nullable=False),
    sa.Column("sent_at", sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_chat_messages")),
    sa.UniqueConstraint("chat_id", "message_id", name="uq_chat_messages_chat_id_message_id")
    )
    op.create_index(op.f("ix_chat_messages_sent_at"), "chat_messages", ["sent_at"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_chat_messages_sent_at"), table_name="chat_messages")
    op.drop_table("chat_messages")
