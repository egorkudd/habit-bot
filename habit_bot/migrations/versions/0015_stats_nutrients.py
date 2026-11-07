"""Какие строки КБЖУ показывать в обзоре «Итогов» (StatsSettings.nutrients, правки 1.0.2)

Revision ID: 0015_stats_nutrients
Revises: 0014_food_catalog_v2
Create Date: 2026-11-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_stats_nutrients"
down_revision = "0014_food_catalog_v2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("stats_settings") as batch_op:
        batch_op.add_column(sa.Column("nutrients", sa.String(length=8), server_default="kp", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("stats_settings") as batch_op:
        batch_op.drop_column("nutrients")
