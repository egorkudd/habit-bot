"""Поддельный Telegram: записывает запросы бота и отвечает как Bot API, без сети."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramForbiddenError
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageReplyMarkup,
    EditMessageText,
    GetMe,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import Chat, Message, User

BOT_USER = User(id=1000001, is_bot=True, first_name="Habit Test", username="habit_test_bot")


class FakeTelegramSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.blocked_chats: set[int] = set()
        self._message_id = 100

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.requests.append(method)
        if isinstance(method, GetMe):
            return BOT_USER
        if isinstance(method, SendMessage):
            chat_id = int(method.chat_id)
            if chat_id in self.blocked_chats:
                raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
            self._message_id += 1
            return Message(
                message_id=self._message_id,
                date=datetime.now(UTC),
                chat=Chat(id=chat_id, type="private"),
                text=method.text,
            )
        if isinstance(method, EditMessageText):
            if method.chat_id is not None and int(method.chat_id) in self.blocked_chats:
                raise TelegramForbiddenError(method=method, message="Forbidden: bot was blocked by the user")
            return True
        return True

    async def stream_content(
        self, url: str, headers: dict[str, Any] | None = None, timeout: int = 30,
        chunk_size: int = 65536, raise_for_status: bool = True,
    ) -> AsyncGenerator[bytes, None]:
        if False:  # pragma: no cover
            yield b""

    # --- удобные выборки для проверок ---
    def sent(self, chat_id: int | None = None) -> list[SendMessage]:
        return [
            m for m in self.requests
            if isinstance(m, SendMessage) and (chat_id is None or int(m.chat_id) == chat_id)
        ]

    def texts(self, chat_id: int) -> list[str]:
        return [m.text for m in self.sent(chat_id)]

    def edits(self) -> list[EditMessageText]:
        return [m for m in self.requests if isinstance(m, EditMessageText)]

    def last(self, chat_id: int) -> SendMessage:
        return self.sent(chat_id)[-1]

    def answers(self) -> list[AnswerCallbackQuery]:
        return [m for m in self.requests if isinstance(m, AnswerCallbackQuery)]

    def markup_removals(self) -> list[EditMessageReplyMarkup]:
        return [m for m in self.requests if isinstance(m, EditMessageReplyMarkup)]


def message_update(update_id: int, user_id: int, text: str, first_name: str = "Егор") -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "date": int(datetime(2026, 11, 3, 12, 0, tzinfo=UTC).timestamp()),
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": user_id, "is_bot": False, "first_name": first_name},
            "text": text,
            **({"entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}]}
               if text.startswith("/") else {}),
        },
    }


def callback_update(update_id: int, user_id: int, data: str, message_id: int = 500) -> dict[str, Any]:
    """Нажатие кнопки под сообщением бота."""
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "chat_instance": "ci",
            "from": {"id": user_id, "is_bot": False, "first_name": "Егор"},
            "data": data,
            "message": {
                "message_id": message_id,
                "date": int(datetime(2026, 11, 3, 12, 0, tzinfo=UTC).timestamp()),
                "chat": {"id": user_id, "type": "private"},
                "from": {"id": BOT_USER.id, "is_bot": True, "first_name": BOT_USER.first_name},
                "text": "…",
            },
        },
    }
