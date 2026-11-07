from __future__ import annotations

from datetime import date

from habit_bot.kernel.identity import Actor
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.days.public import DayEntry
from habit_bot.modules.warmup.usecases import Warmup


class WarmupModule(Module):
    """Зарядка (раздел 3.3, часть 6): набор и шаги, зарядки, личные цели, строка карточки дня."""

    key = "warmup"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        days = ctx.services["days"]
        warmup = Warmup(uow=ctx.uow, clock=ctx.clock, idempotency=ctx.idempotency,
                        profiles=ctx.services["users.profiles"])
        ctx.services["warmup"] = warmup
        days.add_mover("warmup", warmup)

        async def listing(actor: Actor, day: date) -> list[DayEntry]:
            return [DayEntry("warmup", s.public_id, f"🤸 Зарядка №{s.number}", f"🤸 Зарядка №{s.number}: {s.summary()}")
                    for s in await warmup.sessions(actor, day)]

        async def remove(actor: Actor, public_id: str) -> bool:
            return await warmup.delete_session(actor, public_id) is not None

        days.add_entries("warmup", listing, remove)

        async def card_section(actor: Actor, day: date) -> list[str]:
            sessions = await warmup.sessions(actor, day)
            if not sessions:
                return []
            return [f"🤸 Зарядка {len(sessions)}/{await warmup.daily_goal(actor)}"]

        days.add_card_section(card_section)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.warmup.telegram.handlers import build_warmup_router

            assert isinstance(channel, TelegramChannel)
            nav, router = build_warmup_router(warmup, days, channel.screens, lambda: channel.day_card)
            channel.add_router(nav, first=True)
            channel.add_router(router)
            channel.menu.mark_ready("warmup")
