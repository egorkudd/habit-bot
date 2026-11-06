"""«🛠 Админ» (раздел 3.13): пользователи без содержимого дневника, блокировка, удаление, расходы на ИИ без
текстов запросов, общий каталог. Администратора нельзя заблокировать или удалить через бота. Без aiogram."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, tzinfo
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import Base, UowFactory
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor, Role, User, UserStatus
from habit_bot.platform.ai.models import AiCommand

# Таблицы «записей дневника» — для числа записей в списке пользователей (само содержимое админ не видит).
RECORD_TABLES = ("food_entry", "warmup_session", "habits_entry", "workouts_session", "runs_entry")


@dataclass(frozen=True, slots=True)
class UserRow:
    user_id: int
    name: str
    role: Role
    status: UserStatus
    registered: date
    last_active: date
    records: int

    @property
    def protected(self) -> bool:
        return self.role is Role.ADMIN


@dataclass(frozen=True, slots=True)
class CostRow:
    name: str
    parses: int
    cost: Decimal


@dataclass(frozen=True, slots=True)
class AiCosts:
    month: str
    total: Decimal
    budget: Decimal
    rows: tuple[CostRow, ...]


class Admin:
    def __init__(self, *, uow: UowFactory, clock: Clock, tz: tzinfo, profiles: Any, food: Any = None,
                 exercises_count: Any = None, budget_usd: Decimal = Decimal(0)) -> None:
        self._uow = uow
        self._clock = clock
        self._tz = tz
        self._profiles = profiles
        self.food = food
        self._exercises_count = exercises_count
        self.budget_usd = budget_usd

    @staticmethod
    def _require(actor: Actor) -> None:
        if not actor.is_admin:
            raise AppError("ACCESS-FOREIGN")

    def _day(self, moment: datetime) -> date:
        return moment.astimezone(self._tz).date()

    async def _records(self, session: Any, user_id: int) -> int:
        total = 0
        for name in RECORD_TABLES:
            table = Base.metadata.tables.get(name)
            if table is None:  # pragma: no cover — все модели MVP подключены в all_models
                continue
            query = select(func.count()).select_from(table).where(table.c.user_id == user_id)
            if "deleted_at" in table.c:
                query = query.where(table.c.deleted_at.is_(None))
            total += int((await session.execute(query)).scalar_one())
        return total

    def _row(self, user: User, records: int) -> UserRow:
        return UserRow(user.id, user.name or "без имени", user.role, user.status, self._day(user.created_at),
                       self._day(user.last_active_at), records)

    async def users(self, actor: Actor) -> list[UserRow]:
        """Все, кроме удалённых: сначала администраторы, затем по дате регистрации."""
        self._require(actor)
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(User).where(User.status != UserStatus.DELETED)
                                              .order_by(User.id))).scalars().all()
            found = [self._row(u, await self._records(uow.session, u.id)) for u in rows]
        return sorted(found, key=lambda r: (not r.protected, r.user_id))

    async def user(self, actor: Actor, user_id: int) -> UserRow | None:
        self._require(actor)
        async with self._uow() as uow:
            user = await uow.session.get(User, user_id)
            if user is None or user.status is UserStatus.DELETED:
                return None
            return self._row(user, await self._records(uow.session, user.id))

    async def set_blocked(self, actor: Actor, user_id: int, blocked: bool) -> UserRow | None:
        """Заблокированный при следующем сообщении получает ACCESS-BLOCKED; данные остаются."""
        self._require(actor)
        async with self._uow() as uow:
            user = await uow.session.get(User, user_id)
            if user is None or user.status is UserStatus.DELETED:
                return None
            if user.role is Role.ADMIN:
                raise AppError("ACCESS-ADMIN-PROTECTED")
            if blocked:
                user.status = UserStatus.BLOCKED
            elif user.status is UserStatus.BLOCKED:
                user.status = UserStatus.ACTIVE
        return await self.user(actor, user_id)

    async def delete_user(self, actor: Actor, user_id: int) -> bool:
        self._require(actor)
        found = await self.user(actor, user_id)
        if found is None:
            return False
        if found.protected:
            raise AppError("ACCESS-ADMIN-PROTECTED")
        await self._profiles.erase_user(user_id)
        return True

    async def ai_costs(self, actor: Actor) -> AiCosts:
        """Расходы на ИИ за текущий месяц — всего и по пользователям; тексты запросов не показываются."""
        self._require(actor)
        now = self._clock.now()
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(User.name, func.count(AiCommand.id), func.coalesce(func.sum(AiCommand.cost_usd), 0))
                .join(User, User.id == AiCommand.user_id).where(AiCommand.created_at >= start)
                .group_by(User.id, User.name).order_by(func.sum(AiCommand.cost_usd).desc())
            )).all()
        costs = tuple(CostRow(name or "без имени", int(n), Decimal(str(c))) for name, n, c in rows)
        total = sum((r.cost for r in costs), Decimal(0))
        return AiCosts(f"{now:%m.%Y}", total, self.budget_usd, costs)

    async def catalog_counts(self, actor: Actor) -> tuple[int, int, int]:
        """Продуктов в каталоге, из них скрыто, упражнений в базе."""
        self._require(actor)
        items = await self.food.catalog(include_hidden=True) if self.food is not None else []
        exercises = await self._exercises_count() if self._exercises_count is not None else 0
        return len(items), sum(not i.active for i in items), exercises
