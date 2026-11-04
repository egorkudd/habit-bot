"""Сброс по бездействию и состояние ввода в каждом апдейте (раздел 3, «Сброс через 15 минут бездействия»).

Проверка идёт и при каждом действии пользователя, и по таймеру, поэтому сброс срабатывает и после перезапуска.
Апдейты одного пользователя обрабатываются по очереди — два быстрых нажатия не перепишут ввод друг другу.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.fsm.context import FSMContext
from aiogram.types import TelegramObject

from habit_bot.channels.telegram.dialogs.fsm import DbFsmStorage, user_key
from habit_bot.channels.telegram.dialogs.policy import DIALOG, ONBOARDING
from habit_bot.kernel.clock import Clock
from habit_bot.kernel.identity import Actor


class UserLocks:
    def __init__(self) -> None:
        self._locks: dict[int, tuple[asyncio.Lock, int]] = {}

    @asynccontextmanager
    async def hold(self, user_id: int) -> AsyncIterator[None]:
        lock, users = self._locks.get(user_id, (asyncio.Lock(), 0))
        self._locks[user_id] = (lock, users + 1)
        try:
            async with lock:
                yield
        finally:
            lock, users = self._locks[user_id]
            if users <= 1:
                del self._locks[user_id]
            else:
                self._locks[user_id] = (lock, users - 1)

    def __len__(self) -> int:
        return len(self._locks)


class ActivityMiddleware(BaseMiddleware):
    """Идёт после входа: сбрасывает просроченный ввод, продлевает остальной и даёт обработчикам ``state``."""

    def __init__(self, storage: DbFsmStorage, clock: Clock) -> None:
        self._storage = storage
        self._clock = clock
        self.locks = UserLocks()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor: Actor | None = data.get("actor")
        bot: Bot | None = data.get("bot")
        if actor is None or bot is None:
            return await handler(event, data)
        async with self.locks.hold(actor.user_id):
            now = self._clock.now()
            store = self._storage.store
            await store.expire(now, actor.user_id)
            await store.touch(actor.user_id, now)
            # Пока идёт анкета, весь ввод относится к ней (раздел 3.0: продолжается с того же шага).
            onboarding = await store.get(actor.user_id, ONBOARDING)
            scope = ONBOARDING if onboarding is not None and onboarding.state else DIALOG
            state = FSMContext(storage=self._storage, key=user_key(bot.id, actor.user_id, scope))
            data["state"] = state
            data["raw_state"] = await state.get_state()
            data["fsm_storage"] = self._storage
            return await handler(event, data)
