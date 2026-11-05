"""Тренировки, база упражнений и бег

Revision ID: 0008_workouts
Revises: 0007_habits
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_workouts"
down_revision = "0007_habits"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("runs_entry",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("day", sa.Date(), nullable=False),
    sa.Column("logged_at", sa.DateTime(), nullable=False),
    sa.Column("distance_km", sa.Float(), nullable=False),
    sa.Column("duration_sec", sa.Integer(), nullable=False),
    sa.Column("pace_sec", sa.Integer(), nullable=False),
    sa.Column("public_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.Column("deleted_at", sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_runs_entry_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_runs_entry")),
    sa.UniqueConstraint("public_id", name=op.f("uq_runs_entry_public_id"))
    )
    with op.batch_alter_table("runs_entry", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_runs_entry_day"), ["day"], unique=False)
        batch_op.create_index(batch_op.f("ix_runs_entry_user_id"), ["user_id"], unique=False)

    op.create_table("workouts_exercise",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=True),
    sa.Column("catalog_key", sa.String(length=32), nullable=True),
    sa.Column("name", sa.String(length=64), nullable=False),
    sa.Column("place", sa.String(length=8), nullable=False),
    sa.Column("equipment", sa.String(length=16), nullable=False),
    sa.Column("group", sa.String(length=16), nullable=False),
    sa.Column("primary", sa.String(length=16), nullable=False),
    sa.Column("secondary", sa.JSON(), nullable=False),
    sa.Column("movement", sa.String(length=16), nullable=False),
    sa.Column("compound", sa.Boolean(), nullable=False),
    sa.Column("difficulty", sa.String(length=16), nullable=False),
    sa.Column("measure", sa.String(length=16), nullable=False),
    sa.Column("floor", sa.Boolean(), nullable=False),
    sa.Column("suggest", sa.String(length=4), nullable=False),
    sa.Column("loaded", sa.Boolean(), nullable=False),
    sa.Column("easier_key", sa.String(length=32), nullable=True),
    sa.Column("harder_key", sa.String(length=32), nullable=True),
    sa.Column("weight_step", sa.Float(), nullable=True),
    sa.Column("reps_low", sa.Integer(), nullable=False),
    sa.Column("reps_high", sa.Integer(), nullable=False),
    sa.Column("per_dumbbell", sa.Boolean(), nullable=False),
    sa.Column("active", sa.Boolean(), nullable=False),
    sa.Column("public_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.Column("version", sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workouts_exercise_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts_exercise")),
    sa.UniqueConstraint("catalog_key", name=op.f("uq_workouts_exercise_catalog_key")),
    sa.UniqueConstraint("public_id", name=op.f("uq_workouts_exercise_public_id"))
    )
    with op.batch_alter_table("workouts_exercise", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workouts_exercise_user_id"), ["user_id"], unique=False)

    op.create_table("workouts_session",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("day", sa.Date(), nullable=False),
    sa.Column("kind", sa.String(length=8), nullable=False),
    sa.Column("status", sa.String(length=8), nullable=False),
    sa.Column("started_at", sa.DateTime(), nullable=False),
    sa.Column("last_action_at", sa.DateTime(), nullable=False),
    sa.Column("finished_at", sa.DateTime(), nullable=True),
    sa.Column("duration_min", sa.Integer(), nullable=True),
    sa.Column("tonnage", sa.Float(), nullable=False),
    sa.Column("band", sa.Boolean(), nullable=True),
    sa.Column("missing", sa.JSON(), nullable=False),
    sa.Column("auto_finished", sa.Boolean(), nullable=False),
    sa.Column("public_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.Column("deleted_at", sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workouts_session_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts_session")),
    sa.UniqueConstraint("public_id", name=op.f("uq_workouts_session_public_id"))
    )
    with op.batch_alter_table("workouts_session", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workouts_session_day"), ["day"], unique=False)
        batch_op.create_index(batch_op.f("ix_workouts_session_user_id"), ["user_id"], unique=False)

    op.create_table("workouts_settings",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("weekly_goal", sa.Integer(), nullable=False),
    sa.Column("bands", sa.JSON(), nullable=False),
    sa.Column("show_all", sa.Boolean(), nullable=False),
    sa.Column("band_last", sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workouts_settings_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts_settings")),
    sa.UniqueConstraint("user_id", name="uq_workouts_settings_user_id")
    )
    op.create_table("workouts_set",
    sa.Column("id", sa.Integer(), nullable=False),
    sa.Column("user_id", sa.Integer(), nullable=False),
    sa.Column("session_id", sa.Integer(), nullable=False),
    sa.Column("exercise_id", sa.Integer(), nullable=True),
    sa.Column("name", sa.String(length=64), nullable=False),
    sa.Column("measure", sa.String(length=16), nullable=False),
    sa.Column("per_dumbbell", sa.Boolean(), nullable=False),
    sa.Column("number", sa.Integer(), nullable=False),
    sa.Column("weight", sa.Float(), nullable=True),
    sa.Column("reps", sa.Integer(), nullable=True),
    sa.Column("seconds", sa.Integer(), nullable=True),
    sa.Column("band", sa.String(length=8), nullable=True),
    sa.Column("public_id", sa.Uuid(), nullable=False),
    sa.Column("created_at", sa.DateTime(), nullable=False),
    sa.Column("updated_at", sa.DateTime(), nullable=False),
    sa.Column("deleted_at", sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(["exercise_id"], ["workouts_exercise.id"], name=op.f("fk_workouts_set_exercise_id_workouts_exercise"), ondelete="SET NULL"),
    sa.ForeignKeyConstraint(["session_id"], ["workouts_session.id"], name=op.f("fk_workouts_set_session_id_workouts_session"), ondelete="CASCADE"),
    sa.ForeignKeyConstraint(["user_id"], ["users.id"], name=op.f("fk_workouts_set_user_id_users"), ondelete="CASCADE"),
    sa.PrimaryKeyConstraint("id", name=op.f("pk_workouts_set")),
    sa.UniqueConstraint("public_id", name=op.f("uq_workouts_set_public_id"))
    )
    with op.batch_alter_table("workouts_set", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_workouts_set_exercise_id"), ["exercise_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_workouts_set_session_id"), ["session_id"], unique=False)



def downgrade() -> None:
    with op.batch_alter_table("workouts_set", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workouts_set_session_id"))
        batch_op.drop_index(batch_op.f("ix_workouts_set_exercise_id"))

    op.drop_table("workouts_set")
    op.drop_table("workouts_settings")
    with op.batch_alter_table("workouts_session", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workouts_session_user_id"))
        batch_op.drop_index(batch_op.f("ix_workouts_session_day"))

    op.drop_table("workouts_session")
    with op.batch_alter_table("workouts_exercise", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_workouts_exercise_user_id"))

    op.drop_table("workouts_exercise")
    with op.batch_alter_table("runs_entry", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_runs_entry_user_id"))
        batch_op.drop_index(batch_op.f("ix_runs_entry_day"))

    op.drop_table("runs_entry")
