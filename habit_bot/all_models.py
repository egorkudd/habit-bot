"""Все модели SQLAlchemy — для Alembic (миграции и проверка ``alembic check``)."""

from habit_bot.channels.telegram.dialogs.models import DialogState
from habit_bot.kernel.db import Base
from habit_bot.kernel.idempotency import IdempotencyKey
from habit_bot.kernel.identity import Identity, User
from habit_bot.modules.days.models import DayStatus
from habit_bot.modules.food.models import FoodEntry, FoodItem
from habit_bot.modules.habits.models import Habit, HabitEntry
from habit_bot.modules.users.models import BodyWeight, Goal, Invite, Profile
from habit_bot.modules.warmup.models import WarmupGoal, WarmupItem, WarmupSession, WarmupSettings, WarmupTemplate
from habit_bot.platform.alerts.models import AdminAlert
from habit_bot.platform.sources.models import SourceCache

__all__ = [
    "AdminAlert", "Base", "BodyWeight", "DayStatus", "DialogState", "FoodEntry", "FoodItem", "Goal", "Habit",
    "HabitEntry", "IdempotencyKey", "Identity", "Invite", "Profile", "SourceCache", "User", "WarmupGoal", "WarmupItem",
    "WarmupSession", "WarmupSettings", "WarmupTemplate"
]
