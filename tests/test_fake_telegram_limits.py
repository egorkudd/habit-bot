"""Поддельный Telegram строг, как настоящий: то, что отклонит Bot API, отклоняется и в тестах."""

from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from tests.conftest import ADMIN_ID
from tests.fakes import html_problem


def _inline(text: str, data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, callback_data=data)]])


@pytest.mark.parametrize(
    ("kwargs", "problem"),
    [
        ({"text": ""}, "message text is empty"),
        ({"text": "x" * 4097}, "message is too long"),
        ({"text": "<pre>карточка", "parse_mode": "HTML"}, "unclosed tag"),
        ({"text": "<div>x</div>", "parse_mode": "HTML"}, "unsupported start tag"),
        ({"text": "x", "reply_markup": _inline(" ", "a")}, "BUTTON_TEXT_EMPTY"),
        ({"text": "x", "reply_markup": _inline("ok", "я" * 33)}, "BUTTON_DATA_INVALID"),
        ({"text": "x", "reply_markup": _inline("я" * 65, "a")}, "BUTTON_TEXT_TOO_LONG"),
        ({"text": "x", "reply_markup": ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text=" ")]])},
         "BUTTON_TEXT_EMPTY"),
    ],
)
async def test_rejects_like_real_telegram(app: Any, kwargs: dict[str, Any], problem: str) -> None:
    """Пустой или длинный текст, битая HTML-разметка, пустая кнопка, данные кнопки длиннее 64 байт — 400."""
    with pytest.raises(TelegramBadRequest, match=problem):
        await app.telegram.bot.send_message(ADMIN_ID, **kwargs)


async def test_accepts_valid_and_long_toast(app: Any) -> None:
    """Корректная разметка проходит; всплывающее уведомление длиннее 200 символов — отклоняется."""
    await app.telegram.bot.send_message(ADMIN_ID, "<pre>24.10, сб</pre> <b>ok</b>", parse_mode="HTML",
                                        reply_markup=_inline("⠀", "d:1:0:noop"))
    with pytest.raises(TelegramBadRequest, match="MESSAGE_TOO_LONG"):
        await app.telegram.bot.answer_callback_query("cb", text="x" * 201)
    assert html_problem("<b>a</i>") == "can't parse entities: unexpected end tag \"i\""
