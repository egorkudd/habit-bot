"""Хранилище незаконченного ввода в базе: переживает перезапуск бота (раздел 7, «Надёжность»)."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import delete, select, update

from habit_bot.channels.telegram.dialogs.models import DialogState
from habit_bot.channels.telegram.dialogs.policy import LOST_DAY, OTHER_DAY, InactivityPolicy
from habit_bot.kernel.db import UowFactory

log = logging.getLogger(__name__)
TOKEN_LIMIT = 2**31 - 1
_KEEP: Any = object()  # «не менять это поле»


def random_token() -> int:
    return secrets.randbelow(TOKEN_LIMIT - 1) + 1


@dataclass(frozen=True, slots=True)
class DialogSnapshot:
    scope: str
    state: str | None
    token: int
    last_action_at: datetime
    data: dict[str, Any] = field(default_factory=dict)
    other_day: date | None = None


class DialogStore:
    """Состояния по паре (пользователь, область). Пустое состояние без данных — строки нет."""

    def __init__(
        self, *, uow: UowFactory, policy: InactivityPolicy | None = None,
        token_factory: Callable[[], int] = random_token,
    ) -> None:
        self._uow = uow
        self.policy = policy or InactivityPolicy()
        self._new_token = token_factory

    async def get(self, user_id: int, scope: str) -> DialogSnapshot | None:
        async with self._uow() as uow:
            row = await self._row(uow.session, user_id, scope)
            if row is None:
                return None
            return DialogSnapshot(row.scope, row.state, row.token, row.last_action_at, dict(row.data), row.other_day)

    async def set_state(self, user_id: int, scope: str, state: str | None, now: datetime) -> None:
        await self._change(user_id, scope, now, state=state)

    async def set_data(self, user_id: int, scope: str, data: dict[str, Any], now: datetime) -> None:
        await self._change(user_id, scope, now, data=dict(data))

    async def set_day(self, user_id: int, scope: str, day: date, now: datetime) -> None:
        """Режим с датой («Другой день»): строка области с выбранной датой."""
        async with self._uow() as uow:
            row = await self._row(uow.session, user_id, scope)
            if row is None:
                uow.session.add(DialogState(
                    user_id=user_id, scope=scope, state="on", data={}, other_day=day, token=self._new_token(),
                    last_action_at=now, version=1,
                ))
                return
            row.state, row.other_day, row.last_action_at = "on", day, now
            row.version += 1

    async def day(self, user_id: int, scope: str) -> date | None:
        snapshot = await self.get(user_id, scope)
        return snapshot.other_day if snapshot else None

    async def clear(self, user_id: int, scope: str) -> bool:
        async with self._uow() as uow:
            result = await uow.session.execute(
                delete(DialogState).where(DialogState.user_id == user_id, DialogState.scope == scope)
            )
            return bool(getattr(result, "rowcount", 0))

    async def active_tokens(self, user_id: int) -> set[int]:
        async with self._uow() as uow:
            rows = await uow.session.execute(select(DialogState.token).where(DialogState.user_id == user_id))
            return set(rows.scalars().all())

    async def touch(self, user_id: int, now: datetime) -> None:
        """Любое сообщение или нажатие продлевает весь незаконченный ввод пользователя (раздел 4.3)."""
        async with self._uow() as uow:
            await uow.session.execute(
                update(DialogState).where(DialogState.user_id == user_id).values(last_action_at=now)
            )

    async def expire(self, now: datetime, user_id: int | None = None) -> list[tuple[int, str]]:
        """Удаляет ввод, где бездействие дольше срока области. Пользователю ничего не присылается."""
        async with self._uow() as uow:
            query = select(DialogState.id, DialogState.user_id, DialogState.scope, DialogState.last_action_at,
                           DialogState.other_day)
            if user_id is not None:
                query = query.where(DialogState.user_id == user_id)
            expired: list[tuple[int, int, str]] = []
            lost: list[tuple[int, date]] = []
            for row_id, owner, scope, last_action_at, other_day in (await uow.session.execute(query)).all():
                ttl = self.policy.ttl_for(scope)
                if ttl is not None and now - last_action_at >= ttl:
                    expired.append((row_id, owner, scope))
                    if scope == OTHER_DAY and other_day is not None:
                        lost.append((owner, other_day))
            if expired:
                await uow.session.execute(delete(DialogState).where(DialogState.id.in_([r[0] for r in expired])))
                log.info("Сброшен незаконченный ввод: %s", len(expired))
            for owner, day in lost:
                # Отметка для следующей записи: «Записываю за сегодня» и кнопка «📅 Нет, за 24.10» (раздел 3).
                uow.session.add(DialogState(
                    user_id=owner, scope=LOST_DAY, state="on", data={}, other_day=day, token=self._new_token(),
                    last_action_at=now, version=1,
                ))
            return [(owner, scope) for _, owner, scope in expired]

    async def _row(self, session: Any, user_id: int, scope: str) -> DialogState | None:
        found = await session.execute(
            select(DialogState).where(DialogState.user_id == user_id, DialogState.scope == scope)
        )
        return found.scalar_one_or_none()  # type: ignore[no-any-return]

    async def _change(
        self, user_id: int, scope: str, now: datetime, *,
        state: str | None = _KEEP, data: dict[str, Any] | None = None,
    ) -> None:
        async with self._uow() as uow:
            row = await self._row(uow.session, user_id, scope)
            new_state = (row.state if row else None) if state is _KEEP else state
            new_data = (dict(row.data) if row else {}) if data is None else data
            if new_state is None and not new_data:
                if row is not None:
                    await uow.session.delete(row)
                return
            if row is None:
                uow.session.add(DialogState(
                    user_id=user_id, scope=scope, state=new_state, data=new_data, token=self._new_token(),
                    last_action_at=now, version=1,
                ))
                return
            row.state = new_state
            row.data = new_data
            row.last_action_at = now
            row.version += 1
