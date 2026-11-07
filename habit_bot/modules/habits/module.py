from __future__ import annotations

from datetime import date
from decimal import Decimal

from habit_bot.kernel.identity import Actor
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.days.public import DayEntry
from habit_bot.modules.habits.domain.habits import STARTER_ON_HOME, format_value, is_scheduled, progress_label
from habit_bot.modules.habits.usecases import Habits


class HabitsModule(Module):
    """Свои привычки (раздел 3.6, часть 7): шаблоны и свои, отметки, список «Привычки», серии, архив."""

    key = "habits"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        profiles = ctx.services["users.profiles"]
        habits = Habits(uow=ctx.uow, clock=ctx.clock, idempotency=ctx.idempotency, profiles=profiles, days=days)
        ctx.services["habits"] = habits
        days.add_mover("habits", habits)

        async def listing(actor: Actor, day: date) -> list[DayEntry]:
            """Каждая отметка отдельно: «👁 Глаза +1 · 13:00» — удаляется по одной."""
            found = []
            for public_id, at, h, value in await habits.day_marks(actor, day):
                mark = f"+{format_value(value, h.measure, h.unit)} · {at.astimezone(days.tz):%H:%M}"
                found.append(DayEntry("habits", public_id, f"{h.label} {mark}", f"{h.emoji} {h.name}: отметка {mark}"))
            return found

        async def remove(actor: Actor, public_id: str) -> bool:
            return await habits.undo(actor, public_id) is not None

        days.add_entries("habits", listing, remove)

        async def card_section(actor: Actor, day: date) -> list[str]:
            """Строка привычек карточки дня: «👁 2/3 · 💧 6/8» — привычки по расписанию этого дня."""
            items = [i for i in await habits.day(actor, day) if is_scheduled(i.habit.weekdays, day)]
            if not items:
                return []
            return [" · ".join(f"{'✅' if i.done else i.habit.emoji} {progress_label(i.fact, i.habit.goal)}"
                               for i in items)]

        days.add_card_section(card_section)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.habits.telegram.handlers import (
                SETTINGS_KEY,
                Builtin,
                build_habits_router,
                home_key,
            )

            assert isinstance(channel, TelegramChannel)
            builtins: list[Builtin] = []
            food = ctx.services.get("food")
            if food is not None:
                async def food_progress(actor: Actor, day: date) -> tuple[Decimal, Decimal | None]:
                    goal = await profiles.goal_on(actor, day)
                    return (await food.totals(actor, day)).fact.kcal, Decimal(goal.kcal) if goal else None

                builtins.append(Builtin("food", "🍽 Еда", food_progress))
            warmup = ctx.services.get("warmup")
            if warmup is not None:
                async def warmup_progress(actor: Actor, day: date) -> tuple[Decimal, Decimal | None]:
                    return Decimal(len(await warmup.sessions(actor, day))), Decimal(await warmup.daily_goal(actor))

                builtins.append(Builtin("warmup", "🤸 Зарядка", warmup_progress))

            async def extras(actor: Actor) -> list[MenuEntry]:
                """Свои привычки для главного экрана. Здесь же — «Примеры привычек» из анкеты: «👁 Глаза» сразу
                встаёт на главный экран (раздел 6.2)."""
                for created in await habits.apply_starter(actor):
                    if created.template_key in STARTER_ON_HOME:
                        await channel.screens.set_on_home(actor, home_key(created), True)
                found = await habits.habits(actor)
                return [MenuEntry(home_key(h), h.label, 500 + h.position, ready=True) for h in found]

            channel.screens.extras = extras
            ctx.services["habits.builtins"] = builtins  # тренировки добавят свою строку (часть 8)
            nav, router = build_habits_router(habits, days, channel.screens, lambda: channel.day_card,
                                              lambda: builtins)
            channel.add_router(nav, first=True)
            channel.add_router(router)
            channel.menu.mark_ready("habits")
            channel.menu.add(MenuEntry(SETTINGS_KEY, "✅ Свои привычки", 30, Place.SETTINGS, ready=True))
