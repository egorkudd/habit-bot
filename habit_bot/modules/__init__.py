"""Модули продукта. Новый модуль — новая строка здесь и ключ в ENABLED_MODULES."""

KNOWN_MODULES: dict[str, str] = {
    "users": "habit_bot.modules.users.module:UsersModule",
    "days": "habit_bot.modules.days.module:DaysModule",
    "food": "habit_bot.modules.food.module:FoodModule",
    "warmup": "habit_bot.modules.warmup.module:WarmupModule",
    "habits": "habit_bot.modules.habits.module:HabitsModule",
}
