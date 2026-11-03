"""Оповещения администратору в Telegram (раздел 7.4.2).

Первое оповещение уходит сразу. Повторы того же кода в том же месте в течение часа не шлют новое
сообщение, а обновляют счётчик в уже отправленном.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta
from typing import Protocol

from sqlalchemy import select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.errors.catalog import admin_message
from habit_bot.platform.alerts.models import AdminAlert

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=1)


class AdminNotifier(Protocol):
    async def send(self, chat_id: int, text: str) -> int | None:
        """Отправляет сообщение, возвращает его id (или ``None``, если не получилось)."""

    async def edit(self, chat_id: int, message_id: int, text: str) -> bool: ...


class AdminAlerter:
    def __init__(
        self, *, uow: UowFactory, clock: Clock, notifier: AdminNotifier, admin_chat_ids: Iterable[int],
    ) -> None:
        self._uow = uow
        self._clock = clock
        self._notifier = notifier
        self._admins = sorted(set(admin_chat_ids))

    async def alert(self, code: str, *, where: str, **params: object) -> None:
        """Отправляет или склеивает оповещение. Сам никогда не падает: ошибка оповещения уходит в лог."""
        try:
            await self._alert(code, where=where, params=params)
        except Exception:
            log.exception("Не удалось отправить оповещение администратору", extra={"code": code})

    async def _alert(self, code: str, *, where: str, params: dict[str, object]) -> None:
        now = self._clock.now()
        fingerprint = f"{code}|{where}|{params.get('signature', '')}"[:255]
        async with self._uow() as uow:
            found = await uow.session.execute(
                select(AdminAlert)
                .where(AdminAlert.fingerprint == fingerprint, AdminAlert.window_start > now - WINDOW)
                .order_by(AdminAlert.window_start.desc())
                .limit(1)
            )
            alert = found.scalar_one_or_none()
            if alert is None:
                text = admin_message(code, {**params, "where": where, "count": 1})
                messages: list[list[int]] = []
                for chat_id in self._admins:
                    message_id = await self._notifier.send(chat_id, text)
                    if message_id is not None:
                        messages.append([chat_id, message_id])
                uow.session.add(AdminAlert(
                    code=code, fingerprint=fingerprint, window_start=now, count=1, text=text, messages=messages,
                ))
                return
            alert.count += 1
            alert.text = admin_message(code, {**params, "where": where, "count": alert.count})
            for chat_id, message_id in alert.messages:
                await self._notifier.edit(chat_id, message_id, alert.text)
