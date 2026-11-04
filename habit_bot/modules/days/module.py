from __future__ import annotations

from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.days.usecases import Days


class DaysModule(Module):
    """Логический день, «Другой день», выходные, карточка дня, перенос записей (раздел 3.7, часть 4)."""

    key = "days"
    stage = Stage.MVP
    depends_on = ("users",)

    def register(self, ctx: ModuleContext) -> None:
        days = Days(uow=ctx.uow, clock=ctx.clock, profiles=ctx.services["users.profiles"])
        ctx.services["days"] = days

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.days.telegram.handlers import build_days_router

            assert isinstance(channel, TelegramChannel)
            # Раньше остальных: «📅 23.10 ✕ Вернуться к сегодня» работает даже посреди ввода.
            channel.add_router(build_days_router(days, channel.screens), first=True)
            channel.menu.mark_ready("other_day")
            channel.menu.mark_ready("day_off")
