"""Учёт расходов на ИИ (раздел 7.2): стоимость запроса, траты за месяц, разборы пользователя за сутки."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select

from habit_bot.kernel.db import UowFactory
from habit_bot.platform.ai.client import LlmReply
from habit_bot.platform.ai.models import AiCommand

# Цены DeepSeek в пиковые часы (раздел 7.2) — считаем по верхней границе, чтобы не превысить бюджет.
PRICE_IN = Decimal("0.30")       # $ за 1 млн токенов на вход
PRICE_CACHED = Decimal("0.003")  # $ за 1 млн токенов из кэша
PRICE_OUT = Decimal("1.20")      # $ за 1 млн токенов на выход
MILLION = Decimal(1_000_000)
DAILY_LIMIT = 50
WARN_SHARE = Decimal("0.8")


def cost(reply: LlmReply) -> Decimal:
    fresh = max(reply.prompt_tokens - reply.cached_tokens, 0)
    total = (Decimal(fresh) * PRICE_IN + Decimal(reply.cached_tokens) * PRICE_CACHED
             + Decimal(reply.completion_tokens) * PRICE_OUT) / MILLION
    return total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Usage:
    spent: Decimal
    budget: Decimal

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.budget

    @property
    def warning(self) -> bool:
        return self.spent >= self.budget * WARN_SHARE


class Budget:
    def __init__(self, *, uow: UowFactory, monthly_usd: Decimal, daily_limit: int = DAILY_LIMIT) -> None:
        self._uow = uow
        self.monthly_usd = monthly_usd
        self.daily_limit = daily_limit

    async def usage(self, now: datetime) -> Usage:
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self._uow() as uow:
            spent = (await uow.session.execute(select(func.coalesce(func.sum(AiCommand.cost_usd), 0)).where(
                AiCommand.created_at >= month_start))).scalar_one()
        return Usage(Decimal(str(spent)).quantize(Decimal("0.01")), self.monthly_usd)

    async def used_today(self, user_id: int, day: date) -> int:
        """Разборы пользователя за логический день (с 04:00)."""
        async with self._uow() as uow:
            return int((await uow.session.execute(select(func.count(AiCommand.id)).where(
                AiCommand.user_id == user_id, AiCommand.day == day))).scalar_one())
