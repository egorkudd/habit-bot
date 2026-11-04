"""Поддельный Telegram: записывает запросы бота и отвечает как Bot API, без сети."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
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


MAX_TEXT = 4096
MAX_CALLBACK_DATA = 64
MAX_BUTTON_TEXT = 64  # практический предел: длиннее Telegram обрезает или отклоняет
MAX_TOAST = 200
HTML_TAGS = {"b", "strong", "i", "em", "u", "ins", "s", "strike", "del", "a", "code", "pre", "tg-spoiler",
             "blockquote", "span"}


class _HtmlCheck(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.errors: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in HTML_TAGS:
            self.errors.append(f"can't parse entities: unsupported start tag \"{tag}\"")
        self.stack.append(tag)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack.pop() != tag:
            self.errors.append(f"can't parse entities: unexpected end tag \"{tag}\"")


def html_problem(text: str) -> str | None:
    checker = _HtmlCheck()
    checker.feed(text)
    checker.close()
    if checker.stack:
        checker.errors.append(f"can't parse entities: unclosed tag \"{checker.stack[-1]}\"")
    return checker.errors[0] if checker.errors else None


def telegram_limits_problem(method: TelegramMethod[Any]) -> str | None:
    """Ограничения Bot API, которые настоящий Telegram проверяет и отклоняет запрос с 400."""
    text = getattr(method, "text", None)
    if isinstance(method, (SendMessage, EditMessageText)):
        if not text or not str(text).strip():
            return "message text is empty"
        if len(str(text)) > MAX_TEXT:
            return "message is too long"
        if getattr(method, "parse_mode", None) == "HTML":
            problem = html_problem(str(text))
            if problem:
                return problem
    if isinstance(method, AnswerCallbackQuery) and text and len(text) > MAX_TOAST:
        return "MESSAGE_TOO_LONG"
    markup = getattr(method, "reply_markup", None)
    for row in getattr(markup, "inline_keyboard", None) or []:
        for button in row:
            if not button.text or not button.text.strip():
                return "BUTTON_TEXT_EMPTY"
            if len(button.text) > MAX_BUTTON_TEXT:
                return "BUTTON_TEXT_TOO_LONG"
            data = button.callback_data
            if data is not None and (not data or len(data.encode()) > MAX_CALLBACK_DATA):
                return "BUTTON_DATA_INVALID"
    for row in getattr(markup, "keyboard", None) or []:
        for button in row:
            if not button.text or not button.text.strip():
                return "BUTTON_TEXT_EMPTY"
    return None


class FakeTelegramSession(BaseSession):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod[Any]] = []
        self.blocked_chats: set[int] = set()
        self._message_id = 100

    async def close(self) -> None:
        return None

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        problem = telegram_limits_problem(method)
        if problem:
            # Настоящий Telegram отвечает 400 Bad Request — поддельный тоже, чтобы ошибка всплыла в тестах.
            raise TelegramBadRequest(method=method, message=f"Bad Request: {problem}")
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


# Ответы Open-Meteo Geocoding (раздел 4.12) в том виде, как их отдаёт настоящий сервис (сверено заданием CI
# «Внешние сервисы», tests/live): регион пишется то «область», то «Область». В обычных тестах сети нет.
GEOCODER_ANSWERS: dict[str, list[dict[str, Any]]] = {
    "кировск": [
        {"name": "Кировск", "latitude": 59.8756, "longitude": 30.9914, "country_code": "RU",
         "admin1": "Ленинградская область"},
        {"name": "Кировск", "latitude": 53.2697, "longitude": 29.4752, "country_code": "BY",
         "admin1": "Могилевская область"},
        {"name": "Кировск", "latitude": 67.6142, "longitude": 33.6717, "country_code": "RU",
         "admin1": "Мурманская Область"},
        {"name": "Кировск", "latitude": 67.6142, "longitude": 33.6717, "country_code": "RU",
         "admin1": "Мурманская Область"},
    ],
    "масква": [],
    "ростов на дону": [
        {"name": "Ростов-на-Дону", "latitude": 47.2313, "longitude": 39.7233, "country_code": "RU",
         "admin1": "Ростовская Область"},
    ],
    "новосибирск": [
        {"name": "Новосибирск", "latitude": 55.0415, "longitude": 82.9346, "country_code": "RU",
         "admin1": "Новосибирская область"},
    ],
    "париж": [
        {"name": "Париж", "latitude": 48.8534, "longitude": 2.3488, "country_code": "FR", "admin1": "Иль-де-Франс"},
    ],
}


class FakeGeocoder:
    """Отвечает записанными ответами; «сломано» — сервис недоступен."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def search(self, name: str) -> list[Any]:
        from habit_bot.modules.users.domain.city import normalize
        from habit_bot.platform.sources.geocoding import GeocoderUnavailable, parse_response

        self.calls.append(name)
        key = normalize(name)
        if key == "сломано":
            raise GeocoderUnavailable
        return parse_response({"results": GEOCODER_ANSWERS[key]} if GEOCODER_ANSWERS.get(key) else {})


class TgChat:
    """Переписка одного пользователя с ботом через поддельный Telegram: текст, нажатия по подписи кнопки."""

    def __init__(self, app: Any, session: FakeTelegramSession, tg_id: int, first_name: str = "Егор") -> None:
        self.app = app
        self.session = session
        self.tg_id = tg_id
        self.first_name = first_name

    def _next_id(self) -> int:
        self.session._message_id += 1
        return self.session._message_id

    async def say(self, text: str) -> str:
        update = message_update(self._next_id(), self.tg_id, text, first_name=self.first_name)
        update["message"]["date"] = int(self.app.ctx.clock.now().timestamp())  # время сообщения = часы теста
        await self.app.telegram.dispatcher.feed_raw_update(self.app.telegram.bot, update)
        return self.texts()[-1] if self.texts() else ""

    async def press_data(self, data: str) -> None:
        update = callback_update(self._next_id(), self.tg_id, data)
        update["callback_query"]["from"]["first_name"] = self.first_name
        await self.app.telegram.dispatcher.feed_raw_update(self.app.telegram.bot, update)

    def find_button(self, label: str) -> str:
        """callback_data кнопки с этой подписью в последнем сообщении, где она есть."""
        markups = [m.reply_markup for m in self.session.requests
                   if isinstance(m, (SendMessage, EditMessageReplyMarkup, EditMessageText))
                   and (not isinstance(m, SendMessage) or int(m.chat_id) == self.tg_id)]
        for markup in reversed(markups):
            for row in getattr(markup, "inline_keyboard", None) or []:
                for button in row:
                    if button.text == label:
                        return str(button.callback_data)
        raise AssertionError(f"Кнопки «{label}» нет")

    async def press(self, label: str) -> str:
        await self.press_data(self.find_button(label))
        return self.texts()[-1] if self.texts() else ""

    def texts(self) -> list[str]:
        return self.session.texts(self.tg_id)

    def keyboard(self) -> list[list[str]]:
        """Клавиатура под полем ввода из последнего сообщения, где она была."""
        for m in reversed(self.session.sent(self.tg_id)):
            rows = getattr(m.reply_markup, "keyboard", None)
            if rows:
                return [[b.text for b in row] for row in rows]
        return []

    def labels(self) -> list[str]:
        markup = self.session.sent(self.tg_id)[-1].reply_markup
        return [b.text for row in getattr(markup, "inline_keyboard", None) or [] for b in row]
