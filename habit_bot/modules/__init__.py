"""Модули продукта. Новый модуль — новая строка здесь и ключ в ENABLED_MODULES."""

KNOWN_MODULES: dict[str, str] = {
    "users": "habit_bot.modules.users.module:UsersModule",
    "days": "habit_bot.modules.days.module:DaysModule",
    "food": "habit_bot.modules.food.module:FoodModule",
    "warmup": "habit_bot.modules.warmup.module:WarmupModule",
    "habits": "habit_bot.modules.habits.module:HabitsModule",
    "runs": "habit_bot.modules.runs.module:RunsModule",
    "workouts": "habit_bot.modules.workouts.module:WorkoutsModule",
    "stats": "habit_bot.modules.stats.module:StatsModule",
    "export": "habit_bot.modules.export.module:ExportModule",
    "admin": "habit_bot.modules.admin.module:AdminModule",
    "backup": "habit_bot.modules.backup.module:BackupModule",
    "ai_commands": "habit_bot.modules.ai_commands.module:AiCommandsModule",
}
