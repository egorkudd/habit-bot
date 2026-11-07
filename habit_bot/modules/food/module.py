from __future__ import annotations

from datetime import date

from habit_bot.kernel.domain.formatting import KBJU_HEADER, format_number, kbju_row
from habit_bot.kernel.identity import Actor
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.days.public import DayEntry
from habit_bot.modules.food.domain.nutrition import Nutrients, quantity_label
from habit_bot.modules.food.usecases import Food


def _line(title: str, n: Nutrients) -> str:
    return kbju_row(title, n.kcal, n.protein, n.fat, n.carbs)


class FoodModule(Module):
    """Еда (раздел 3.2, часть 5): каталог, свои рецепты и продукты, записи, строки карточки дня."""

    key = "food"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        profiles = ctx.services["users.profiles"]
        days = ctx.services["days"]
        food = Food(uow=ctx.uow, clock=ctx.clock, idempotency=ctx.idempotency, profiles=profiles)
        ctx.services["food"] = food
        days.add_mover("food", food)

        async def listing(actor: Actor, day: date) -> list[DayEntry]:
            found = []
            for e in await food.entries(actor, day):
                amount = quantity_label(e.unit, e.quantity, e.portion_label)
                n = e.nutrients
                values = (f"{format_number(n.kcal)} ккал · Б {format_number(n.protein)} · Ж {format_number(n.fat)} · "
                          f"У {format_number(n.carbs)}")
                found.append(DayEntry("food", e.public_id, f"🍽 {e.name} · {format_number(n.kcal)} ккал",
                                      f"🍽 {e.name} — {amount}: {values}"))
            return found

        async def remove(actor: Actor, public_id: str) -> bool:
            return await food.delete_entry(actor, public_id) is not None

        days.add_entries("food", listing, remove)

        async def card_section(actor: Actor, day: date) -> list[str]:
            """Факт / Остаток по цели, действовавшей в эту дату, и расход в рублях (раздел 3.1, 4.2)."""
            totals = await food.totals(actor, day)
            if not totals.count:
                return []
            goal = await profiles.goal_on(actor, day)
            lines = [] if goal is not None else [KBJU_HEADER]  # с целью заголовок таблицы уже над строкой «Цель»
            lines.append(_line("Факт", totals.fact))
            if goal is not None:
                lines.append(_line("Остаток", Nutrients(*goal.values()) - totals.fact))
            cost = f"Расход: {format_number(totals.cost)} ₽"
            if totals.without_price:
                cost += f" · {totals.without_price} без цены"
            lines.append(cost)
            return lines

        days.add_card_section(card_section)

        async def seed() -> None:
            await food.seed_catalog()

        ctx.on_startup(seed)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.food.telegram.handlers import build_food_router

            assert isinstance(channel, TelegramChannel)
            nav, router = build_food_router(food, days, channel.screens, lambda: channel.day_card)
            channel.add_router(nav, first=True)
            channel.add_router(router)
            channel.menu.mark_ready("food")
            channel.menu.add(MenuEntry("food_items", "🍽 Рецепты и продукты", 10, Place.SETTINGS, ready=True))
