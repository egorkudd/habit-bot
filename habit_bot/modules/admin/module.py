from __future__ import annotations

from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.admin.usecases import Admin


class AdminModule(Module):
    """«🛠 Админ» (раздел 3.13, часть 10): пользователи, блокировка, удаление, расходы на ИИ, общий каталог.
    Приглашения остаются в модуле users."""

    key = "admin"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        food = ctx.services.get("food")
        workouts = ctx.services.get("workouts")
        admin = Admin(uow=ctx.uow, clock=ctx.clock, tz=ctx.services["days"].tz,
                      profiles=ctx.services["users.profiles"], food=food,
                      exercises_count=workouts.catalog_count if workouts is not None else None,
                      budget_usd=ctx.settings.llm_monthly_budget_usd)
        ctx.services["admin"] = admin

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.admin.telegram.handlers import (
                AI_KEY,
                CATALOG_KEY,
                USERS_KEY,
                build_admin_tools_router,
            )

            assert isinstance(channel, TelegramChannel)
            channel.add_router(build_admin_tools_router(admin, channel.screens))
            channel.menu.add(MenuEntry(USERS_KEY, "👥 Пользователи", 10, Place.ADMIN, admin_only=True, ready=True))
            channel.menu.add(MenuEntry(AI_KEY, "💰 Расходы на ИИ", 20, Place.ADMIN, admin_only=True, ready=True))
            if food is not None:
                channel.menu.add(MenuEntry(CATALOG_KEY, "📚 Каталог", 30, Place.ADMIN, admin_only=True, ready=True))
