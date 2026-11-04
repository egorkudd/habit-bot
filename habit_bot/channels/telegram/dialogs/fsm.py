"""Хранилище состояний aiogram поверх ``DialogStore``.

Ключ строится не по Telegram-ID, а по ``user_id`` пользователя бота (Telegram-ID хранится только в Identity).
``destiny`` ключа — область ввода: «default» → «dialog», остальные — как есть («onboarding», «workout»…).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.fsm.storage.base import DEFAULT_DESTINY, BaseStorage, StateType, StorageKey

from habit_bot.channels.telegram.dialogs.policy import DIALOG
from habit_bot.channels.telegram.dialogs.store import DialogStore
from habit_bot.kernel.clock import Clock


def scope_of(key: StorageKey) -> str:
    return DIALOG if key.destiny == DEFAULT_DESTINY else key.destiny


def user_key(bot_id: int, user_id: int, scope: str = DIALOG) -> StorageKey:
    destiny = DEFAULT_DESTINY if scope == DIALOG else scope
    return StorageKey(bot_id=bot_id, chat_id=user_id, user_id=user_id, destiny=destiny)


class DbFsmStorage(BaseStorage):
    def __init__(self, store: DialogStore, clock: Clock) -> None:
        self.store = store
        self._clock = clock

    async def set_state(self, key: StorageKey, state: StateType = None) -> None:
        value = state.state if isinstance(state, State) else state
        await self.store.set_state(key.user_id, scope_of(key), value, self._clock.now())

    async def get_state(self, key: StorageKey) -> str | None:
        snapshot = await self.store.get(key.user_id, scope_of(key))
        return snapshot.state if snapshot else None

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        await self.store.set_data(key.user_id, scope_of(key), dict(data), self._clock.now())

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        snapshot = await self.store.get(key.user_id, scope_of(key))
        return dict(snapshot.data) if snapshot else {}

    async def token(self, key: StorageKey) -> int:
        """Номер текущего ввода для кнопок; 0 — ввода нет (кнопки не устаревают)."""
        snapshot = await self.store.get(key.user_id, scope_of(key))
        return snapshot.token if snapshot else 0

    async def close(self) -> None:
        return None


def context_for(state: FSMContext, scope: str) -> FSMContext:
    """Состояние той же пары «бот — пользователь» в другой области ввода (например, анкеты)."""
    key = user_key(state.key.bot_id, state.key.user_id, scope)
    return FSMContext(storage=state.storage, key=key)


def scope_of_context(state: FSMContext) -> str:
    return scope_of(state.key)


async def start_dialog(state: FSMContext, new_state: State, day: date | None = None) -> int:
    """Начинает новый ввод с чистого листа: у него новый номер, кнопки прошлого ввода устаревают.

    ``day`` — дата записи на момент начала ввода: ввод, начатый в 03:58 и законченный в 04:02, остаётся
    в предыдущем дне (раздел 4.3).
    """
    await state.clear()
    if day is not None:
        await state.set_data({"_day": day.isoformat()})
    await state.set_state(new_state)
    return await dialog_token(state)


async def dialog_token(state: FSMContext) -> int:
    storage = state.storage
    assert isinstance(storage, DbFsmStorage)
    return await storage.token(state.key)
