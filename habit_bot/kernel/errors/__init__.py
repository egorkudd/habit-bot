"""Ошибки приложения: код из каталога + параметры для текста."""

from __future__ import annotations

import secrets

from habit_bot.kernel.errors.catalog import CATALOG, user_message


class AppError(Exception):
    """Ожидаемая ошибка с кодом из каталога (раздел 7.4).

    Сценарии бросают её вместо текста: канал сам решает, как показать сообщение.
    """

    def __init__(self, code: str, **params: object) -> None:
        if code not in CATALOG:
            raise KeyError(f"Код ошибки {code} не описан в каталоге")
        super().__init__(code)
        self.code = code
        self.params = params

    def user_text(self) -> str:
        return user_message(self.code, self.params)


def new_incident_id() -> str:
    """Код инцидента для внутренней ошибки: «E-7F3A»."""
    return f"E-{secrets.token_hex(2).upper()}"
