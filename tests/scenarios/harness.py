"""Поведенческие сценарии: «живой» пользователь в поддельном Telegram.

Пользователь пишет текст, нажимает кнопки по подписи (под сообщением или на клавиатуре внизу), отправляет стикер,
ждёт — а «мир» умеет переводить часы, запускать фоновые задачи и перезапускать бота на той же базе.
Сети нет: Telegram, геокодер и время — поддельные.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from habit_bot.app import App, build_app
from tests.fakes import FakeTelegramSession, TgChat, callback_update, message_update


class Persona(TgChat):
    """Один пользователь Telegram. Методы возвращают последний ответ бота."""

    def __init__(self, world: World, tg_id: int, first_name: str) -> None:
        super().__init__(world.app, world.session, tg_id, first_name)
        self.world = world
        self._mark = 0

    # --- действия ---
    async def say(self, text: str) -> str:
        self.app = self.world.app  # после перезапуска бота — уже новый экземпляр
        self.mark()
        return await super().say(text)

    async def tap(self, label: str) -> str:
        """Нажать кнопку с подписью: под сообщением (inline) или внизу (клавиатура = отправка текста)."""
        self.app = self.world.app
        self.mark()
        if any(label in row for row in self.keyboard()) and not self._has_inline(label):
            return await super().say(label)
        return await self.press(label)

    async def tap_twice(self, label: str) -> None:
        """Двойное нажатие: Telegram доставляет то же нажатие повторно."""
        self.app = self.world.app
        self.mark()
        update = callback_update(self._next_id(), self.tg_id, self.find_button(label))
        for _ in range(2):
            await self.app.telegram.dispatcher.feed_raw_update(self.app.telegram.bot, dict(update))

    async def sticker(self) -> str:
        self.app = self.world.app
        self.mark()
        update = message_update(self._next_id(), self.tg_id, "x", first_name=self.first_name)
        message = update["message"]
        del message["text"]
        message["date"] = int(self.world.clock.now().timestamp())
        message["sticker"] = {"file_id": "s1", "file_unique_id": "u1", "type": "regular", "width": 512,
                              "height": 512, "is_animated": False, "is_video": False}
        await self.app.telegram.dispatcher.feed_raw_update(self.app.telegram.bot, update)
        return self.last()

    # --- что видит пользователь ---
    def mark(self) -> None:
        self._mark = len(self.texts())

    def replies(self) -> list[str]:
        """Все ответы бота на последнее действие."""
        return self.texts()[self._mark:]

    def last(self) -> str:
        return self.texts()[-1] if self.texts() else ""

    def sees(self, label: str) -> bool:
        """Кнопка с подписью есть под последними сообщениями или на клавиатуре."""
        return self._has_inline(label) or any(label in row for row in self.keyboard())

    def _has_inline(self, label: str) -> bool:
        try:
            self.find_button(label)
        except AssertionError:
            return False
        return True


class World:
    """Бот, часы и база одного сценария. ``restart()`` — перезапуск контейнера с той же базой."""

    def __init__(self, settings: Any, session: FakeTelegramSession, clock: Any, geocoder: Any) -> None:
        self.settings = settings
        self.session = session
        self.clock = clock
        self.geocoder = geocoder
        self.app: App = build_app(settings, telegram_session=session, clock=clock, geocoder=geocoder)
        self.people: list[Persona] = []

    async def start(self) -> World:
        await self.app.startup()
        return self

    async def stop(self) -> None:
        await self.app.close()

    async def restart(self) -> None:
        await self.app.close()
        self.app = build_app(self.settings, telegram_session=self.session, clock=self.clock, geocoder=self.geocoder)
        await self.app.startup()  # при старте сразу сбрасывается просроченный ввод

    def person(self, tg_id: int, first_name: str) -> Persona:
        persona = Persona(self, tg_id, first_name)
        self.people.append(persona)
        return persona

    async def wait(self, **delta: float) -> None:
        """Пользователь ничего не делает; раз в минуту работает задача сброса незаконченного ввода."""
        self.clock.advance(**delta)
        await self.app.telegram.expire_idle()

    def set_time(self, moment: datetime) -> None:
        self.clock.current = moment.astimezone(UTC)

    def service(self, name: str) -> Any:
        return self.app.ctx.services[name]


MSK = timedelta(hours=3)
