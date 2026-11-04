"""Еда: продукты и рецепты (общий каталог и свои), записи еды

Revision ID: 0005_food
Revises: 0004_days
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_food"
down_revision = "0004_days"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "food_item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("catalog_key", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("composition", sa.Text(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("portion_label", sa.String(length=32), nullable=True),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.Column("carbs", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("source_catalog_id", sa.Integer(), nullable=True),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_food_item_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_item")),
        sa.UniqueConstraint("catalog_key", name=op.f("uq_food_item_catalog_key")),
        sa.UniqueConstraint("public_id", name=op.f("uq_food_item_public_id")),
    )
    op.create_index(op.f("ix_food_item_user_id"), "food_item", ["user_id"], unique=False)
    op.create_table(
        "food_entry",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("logged_at", sa.DateTime(), nullable=False),
        sa.Column("food_item_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("portion_label", sa.String(length=32), nullable=True),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.Column("carbs", sa.Float(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["food_item_id"], ["food_item.id"], name=op.f("fk_food_entry_food_item_id_food_item"),
                                ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_food_entry_user_id_users"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_food_entry")),
        sa.UniqueConstraint("public_id", name=op.f("uq_food_entry_public_id")),
    )
    op.create_index(op.f("ix_food_entry_day"), "food_entry", ["day"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_food_entry_day"), table_name="food_entry")
    op.drop_table("food_entry")
    op.drop_index(op.f("ix_food_item_user_id"), table_name="food_item")
    op.drop_table("food_item")
