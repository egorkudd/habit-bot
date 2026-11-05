from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from habit_bot.kernel.domain.formatting import format_number
from habit_bot.kernel.identity import Actor
from habit_bot.kernel.jobs import JobSpec
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.workouts.domain.training import KIND_LABELS
from habit_bot.modules.workouts.usecases import Workouts

AUTO_FINISH_EVERY = timedelta(minutes=1)


class WorkoutsModule(Module):
    """Тренировки (раздел 3.4.0, часть 8): база упражнений, зал / площадка / свободная, подходы, тоннаж,
    автозавершение через 3 часа, цель «тренировок в неделю» (бег тоже считается)."""

    key = "workouts"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        workouts = Workouts(uow=ctx.uow, clock=ctx.clock, idempotency=ctx.idempotency,
                            profiles=ctx.services["users.profiles"])
        ctx.services["workouts"] = workouts
        days.add_mover("workout", workouts)

        async def week_progress(actor: Actor, day: date) -> tuple[int, int]:
            """Тренировки и забеги за неделю (с понедельника) и цель «тренировок в неделю»."""
            start, end = workouts.week(day)
            done = await workouts.count_between(actor, start, end)
            runs = ctx.services.get("runs")
            if runs is not None:
                done += await runs.count_between(actor, start, end)
            return done, (await workouts.settings(actor)).weekly_goal

        ctx.services["workouts.week"] = week_progress

        async def card_section(actor: Actor, day: date) -> list[str]:
            return [f"{KIND_LABELS[s.kind]} {s.duration_min} мин"
                    + (f" · {format_number(s.tonnage)} кг" if s.tonnage else "")
                    for s in await workouts.day_sessions(actor, day)]

        days.add_card_section(card_section)

        async def auto_finish() -> int:
            return await workouts.auto_finish(ctx.clock.now())

        ctx.add_job(JobSpec("workouts.auto_finish", AUTO_FINISH_EVERY, auto_finish))
        async def seed() -> None:
            await workouts.seed_catalog()

        ctx.on_startup(seed)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.workouts.telegram.handlers import SETTINGS_KEY, build_workouts_router

            assert isinstance(channel, TelegramChannel)
            nav, router = build_workouts_router(workouts, days, channel.screens, lambda: channel.day_card,
                                                week_progress)
            channel.add_router(nav, first=True)
            channel.add_router(router)
            channel.menu.mark_ready("workout")
            channel.menu.add(MenuEntry(SETTINGS_KEY, "🏋️ Тренировки", 40, Place.SETTINGS, ready=True))
            builtins = ctx.services.get("habits.builtins")
            if builtins is not None:
                from habit_bot.modules.habits.telegram.handlers import Builtin

                async def progress(actor: Actor, day: date) -> tuple[Decimal, Decimal | None]:
                    done, goal = await week_progress(actor, day)
                    return Decimal(done), Decimal(goal)

                builtins.append(Builtin("workout", "🏋️ Тренировки за неделю", progress))
