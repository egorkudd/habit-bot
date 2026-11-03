"""Профиль, цели КБЖУ, приглашения, вес тела; кэш внешних источников

Revision ID: 0003_users_profile
Revises: 0002_dialog_states
Create Date: 2026-11-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_users_profile"
down_revision = "0002_dialog_states"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("sex", sa.String(length=8), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("height_cm", sa.Float(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("activity", sa.String(length=16), nullable=False),
        sa.Column("goal_mode", sa.String(length=16), nullable=False),
        sa.Column("target_weight", sa.Float(), nullable=True),
        sa.Column("experience", sa.String(length=16), nullable=False),
        sa.Column("city_name", sa.String(length=128), nullable=True),
        sa.Column("city_region", sa.String(length=128), nullable=True),
        sa.Column("city_lat", sa.Float(), nullable=True),
        sa.Column("city_lon", sa.Float(), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("starter_kit", sa.JSON(), nullable=False),
        sa.Column("bands", sa.JSON(), nullable=False),
        sa.Column("has_small_plates", sa.Boolean(), nullable=False),
        sa.Column("show_all_exercises", sa.Boolean(), nullable=False),
        sa.Column("ask_feeling", sa.Boolean(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_users_profile_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users_profile")),
        sa.UniqueConstraint("public_id", name=op.f("uq_users_profile_public_id")),
        sa.UniqueConstraint("user_id", name=op.f("uq_users_profile_user_id")),
    )
    op.create_table(
        "users_goal",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein", sa.Float(), nullable=False),
        sa.Column("fat", sa.Float(), nullable=False),
        sa.Column("carbs", sa.Float(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=True),
        sa.Column("target_weight", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_users_goal_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users_goal")),
        sa.UniqueConstraint("public_id", name=op.f("uq_users_goal_public_id")),
    )
    op.create_index(op.f("ix_users_goal_user_id"), "users_goal", ["user_id"], unique=False)
    op.create_table(
        "users_invite",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("max_uses", sa.Integer(), nullable=False),
        sa.Column("uses", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_users_invite_created_by_users"),
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users_invite")),
        sa.UniqueConstraint("code", name=op.f("uq_users_invite_code")),
        sa.UniqueConstraint("public_id", name=op.f("uq_users_invite_public_id")),
    )
    op.create_table(
        "users_body_weight",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("public_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_users_body_weight_user_id_users"),
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users_body_weight")),
        sa.UniqueConstraint("public_id", name=op.f("uq_users_body_weight_public_id")),
        sa.UniqueConstraint("user_id", "day", name="uq_users_body_weight_user_id_day"),
    )
    op.create_table(
        "source_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_cache")),
        sa.UniqueConstraint("source", "key", name="uq_source_cache_source_key"),
    )


def downgrade() -> None:
    op.drop_table("source_cache")
    op.drop_table("users_body_weight")
    op.drop_table("users_invite")
    op.drop_index(op.f("ix_users_goal_user_id"), table_name="users_goal")
    op.drop_table("users_goal")
    op.drop_table("users_profile")
