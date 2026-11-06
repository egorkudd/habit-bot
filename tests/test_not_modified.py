"""Правка без изменений («message is not modified») — успех; остальные ошибки Telegram не скрываются."""

from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageReplyMarkup, EditMessageText, SendMessage

from habit_bot.channels.telegram.ui.not_modified import IgnoreNotModified

NOT_MODIFIED = "Bad Request: message is not modified: specified new message content and reply markup are the same"


def failing(message: str) -> Any:
    async def make_request(bot: Any, method: Any) -> Any:
        raise TelegramBadRequest(method=method, message=message)
    return make_request


async def test_not_modified_edit_is_success() -> None:
    middleware = IgnoreNotModified()
    edits = (EditMessageText(chat_id=1, message_id=2, text="x"), EditMessageReplyMarkup(chat_id=1, message_id=2))
    for method in edits:
        assert await middleware(failing(NOT_MODIFIED), None, method) is True  # type: ignore[arg-type]


@pytest.mark.parametrize(("method", "message"), [
    (EditMessageText(chat_id=1, message_id=2, text="x"), "Bad Request: message to edit not found"),
    (SendMessage(chat_id=1, text="x"), NOT_MODIFIED),
])
async def test_other_errors_are_raised(method: Any, message: str) -> None:
    with pytest.raises(TelegramBadRequest):
        await IgnoreNotModified()(failing(message), None, method)  # type: ignore[arg-type]
