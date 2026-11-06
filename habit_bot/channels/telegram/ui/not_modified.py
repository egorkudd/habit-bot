"""«message is not modified»: правка сообщения, после которой текст и кнопки те же самые («−5» при нуле, двойное
нажатие «✏️ Изменить»). Telegram отвечает ошибкой 400, но для бота это успех — экран и так верный. Без этой
прослойки каждый такой случай становился внутренней ошибкой E-xxxx у пользователя и оповещением администратору."""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.client.session.middlewares.base import BaseRequestMiddleware, NextRequestMiddlewareType
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import (
    EditMessageCaption,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
    Response,
    TelegramMethod,
)
from aiogram.methods.base import TelegramType

log = logging.getLogger(__name__)
EDITS = (EditMessageText, EditMessageReplyMarkup, EditMessageMedia, EditMessageCaption)


def is_not_modified(error: TelegramBadRequest) -> bool:
    return "message is not modified" in str(error.message).lower()


class IgnoreNotModified(BaseRequestMiddleware):
    async def __call__(
        self, make_request: NextRequestMiddlewareType[TelegramType], bot: Bot,
        method: TelegramMethod[TelegramType],
    ) -> Response[TelegramType]:
        try:
            return await make_request(bot, method)
        except TelegramBadRequest as error:
            if not isinstance(method, EDITS) or not is_not_modified(error):
                raise
            log.debug("Правка без изменений пропущена: %s", type(method).__name__)
            return True  # type: ignore[return-value]  # как ответ Telegram на удачную правку
