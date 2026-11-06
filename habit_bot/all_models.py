"""Все модели SQLAlchemy — для Alembic (миграции и проверка ``alembic check``)."""

from habit_bot.channels.telegram.dialogs.models import DialogState
from habit_bot.channels.telegram.ui.chat_log import ChatMessage
from habit_bot.kernel.db import Base
from habit_bot.kernel.idempotency import IdempotencyKey
from habit_bot.kernel.identity import Identity, User
from habit_bot.modules.days.models import DayStatus
from habit_bot.modules.food.models import FoodEntry, FoodItem
from habit_bot.modules.habits.models import Habit, HabitEntry
from habit_bot.modules.runs.models import RunEntry
from habit_bot.modules.stats.models import StatsSettings
from habit_bot.modules.users.models import BodyWeight, Goal, Invite, Profile
from habit_bot.modules.warmup.models import WarmupGoal, WarmupItem, WarmupSession, WarmupSettings, WarmupTemplate
from habit_bot.modules.workouts.models import Exercise, WorkoutSession, WorkoutSet, WorkoutSettings
from habit_bot.platform.ai.models import AiCommand
from habit_bot.platform.alerts.models import AdminAlert
from habit_bot.platform.backup.models import BackupLog
from habit_bot.platform.sources.models import SourceCache

__all__ = [
    "AdminAlert",
    "AiCommand",
    "BackupLog",
    "Base",
    "BodyWeight",
    "ChatMessage",
    "DayStatus",
    "DialogState",
    "Exercise",
    "FoodEntry",
    "FoodItem",
    "Goal",
    "Habit",
    "HabitEntry",
    "IdempotencyKey",
    "Identity",
    "Invite",
    "Profile",
    "RunEntry",
    "SourceCache",
    "StatsSettings",
    "User",
    "WarmupGoal",
    "WarmupItem",
    "WarmupSession",
    "WarmupSettings",
    "WarmupTemplate",
    "WorkoutSession",
    "WorkoutSet",
    "WorkoutSettings",
]
