"""Проверка кнопок перед обработчиком (раздел 4.4 и раздел 3, устаревание кнопок).

* Владелец в данных кнопки не совпадает с нажавшим — отказ ``ACCESS-FOREIGN``, ничего не меняется.
* Ввод, к которому относится кнопка, сброшен, отменён или закончен — ``UI-STALE`` и главное меню.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, Bot
from aiogram.types import CallbackQuery, TelegramObject

from habit_bot.channels.telegram.dialogs.fsm import DbFsmStorage
from habit_bot.channels.telegram.ui.callbacks import owner_and_token
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.identity import Actor

log = logging.getLogger(__name__)


class CallbackGuardMiddleware(BaseMiddleware):
    def __init__(self, storage: DbFsmStorage, screens: Screens) -> None:
        self._storage = storage
        self._screens = screens

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        actor: Actor | None = data.get("actor")
        bot: Bot | None = data.get("bot")
        checked = owner_and_token(data.get("callback_data"))
        if actor is None or bot is None or checked is None or not isinstance(event, CallbackQuery):
            return await handler(event, data)
        owner, token = checked
        if owner != actor.user_id:
            log.warning("Чужая кнопка отклонена", extra={"code": "ACCESS-FOREIGN", "user": actor.user_id})
            await self._screens.refuse_button(bot, event, actor, "ACCESS-FOREIGN")
            return None
        if token and token not in await self._storage.store.active_tokens(actor.user_id):
            await self._screens.refuse_button(bot, event, actor, "UI-STALE")
            return None
        return await handler(event, data)
