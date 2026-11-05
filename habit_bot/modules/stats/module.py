from __future__ import annotations

from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.stats.usecases import Sources, Stats


class StatsModule(Module):
    """«📊 Итоги» (раздел 3.8, часть 10): картинка дня по выбранной привычке и обзор-светофор за период."""

    key = "stats"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        sources = Sources(profiles=ctx.services["users.profiles"], days=days, food=ctx.services.get("food"),
                          warmup=ctx.services.get("warmup"), habits=ctx.services.get("habits"),
                          workouts=ctx.services.get("workouts"), runs=ctx.services.get("runs"))
        stats = Stats(uow=ctx.uow, clock=ctx.clock, tz=days.tz, sources=sources)
        ctx.services["stats"] = stats

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.stats.telegram.handlers import build_stats_router

            assert isinstance(channel, TelegramChannel)
            nav, router = build_stats_router(stats, channel.screens)
            channel.add_router(nav, first=True)
            channel.add_router(router)
            channel.menu.mark_ready("stats")
