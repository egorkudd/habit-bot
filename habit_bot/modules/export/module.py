from __future__ import annotations

from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.export.usecases import Export, Sources


class ExportModule(Module):
    """Экспорт своих данных в CSV (раздел 3.12, часть 10): таблицы галочками, README.csv, «Одним архивом»."""

    key = "export"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        sources = Sources(profiles=ctx.services["users.profiles"], days=days, food=ctx.services.get("food"),
                          warmup=ctx.services.get("warmup"), habits=ctx.services.get("habits"),
                          workouts=ctx.services.get("workouts"), runs=ctx.services.get("runs"))
        export = Export(clock=ctx.clock, tz=days.tz, sources=sources)
        ctx.services["export"] = export

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.export.telegram.handlers import KEY, build_export_router

            assert isinstance(channel, TelegramChannel)
            channel.add_router(build_export_router(export, channel.screens))
            channel.menu.add(MenuEntry(KEY, "📦 Экспорт", 90, Place.SETTINGS, ready=True))
