"""Часть 2, раздел 3 и критерии раздела 9 «Сброс незаконченного ввода», «Изоляция»: отмена, сброс через 15 минут,
устаревшие и чужие кнопки, главное меню и «Ещё»."""

from typing import Any

from sqlalchemy import select

from habit_bot.app import build_app
from habit_bot.channels.telegram.dialogs.input_check import FINISHED, STEP_DATE, STEP_HEIGHT, STEP_TIME
from habit_bot.channels.telegram.dialogs.models import DialogState
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, StepCb
from habit_bot.channels.telegram.ui.menu import MenuEntry
from habit_bot.channels.telegram.ui.routes import CANCELLED, MORE_TITLE, NOT_UNDERSTOOD, NOTHING_TO_CANCEL
from habit_bot.kernel.identity import User
from tests.conftest import ADMIN_ID, register_active
from tests.fakes import callback_update, message_update

NOT_TRAIL = select(DialogState).where(DialogState.scope != "trail")  # след сообщений — не ввод

STALE = "Это меню устарело. Вот главное меню 👇"
FOREIGN = "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"


class Chat:
    """Переписка владельца с ботом через поддельный Telegram."""

    def __init__(self, app: Any, fake_session: Any) -> None:
        self.app = app
        self.session = fake_session
        self.update_id = 0

    async def say(self, text: str) -> str:
        self.update_id += 1
        update = message_update(self.update_id, ADMIN_ID, text)
        update["message"]["date"] = int(self.app.ctx.clock.now().timestamp())
        await self.app.telegram.dispatcher.feed_raw_update(self.app.telegram.bot, update)
        return self.session.texts(ADMIN_ID)[-1]

    async def press(self, data: str) -> None:
        self.update_id += 1
        await self.app.telegram.dispatcher.feed_raw_update(
            self.app.telegram.bot, callback_update(self.update_id, ADMIN_ID, data))

    def texts(self) -> list[str]:
        return self.session.texts(ADMIN_ID)

    async def states(self) -> list[DialogState]:
        async with self.app.ctx.uow() as uow:
            return list((await uow.session.execute(NOT_TRAIL)).scalars().all())

    async def token(self) -> int:
        (row,) = await self.states()
        return row.token

    async def user_id(self) -> int:
        async with self.app.ctx.uow() as uow:
            return int((await uow.session.execute(select(User.id))).scalar_one())


async def _chat(app: Any, fake_session: Any) -> Chat:
    await register_active(app)
    chat = Chat(app, fake_session)
    await chat.say("/start")
    return chat


def _labels(markup: Any) -> list[list[str]]:
    rows = getattr(markup, "keyboard", None) or markup.inline_keyboard
    return [[button.text for button in row] for row in rows]


async def test_start_shows_main_menu(app: Any, fake_session: Any) -> None:
    """Раздел 3.1: клавиатура по умолчанию — Еда, Зарядка, Тренировка, Привычки, Итоги, Ещё; по 2 в ряд."""
    await _chat(app, fake_session)
    assert _labels(fake_session.last(ADMIN_ID).reply_markup) == [
        ["🍽 Еда", "🤸 Зарядка"], ["🏋️ Тренировка", "✅ Привычки"], ["📊 Итоги", "🏠 Домой", "☰ Ещё"],
    ]


FUTURE = MenuEntry("future", "🔮 Новое", 60, part=11)


async def test_menu_buttons_answer_soon(app: Any, fake_session: Any) -> None:
    """Результат части 2: раздел, которого ещё нет, отвечает «скоро» с номером части плана (с части 10 все разделы
    MVP готовы — проверяем на будущем)."""
    app.telegram.menu.add(FUTURE)
    chat = await _chat(app, fake_session)
    assert await chat.say("🔮 Новое") == "🔮 Новое — скоро: раздел появится в части 11 плана."
    assert await chat.say("🔮 Новое") == "🔮 Новое — скоро: раздел появится в части 11 плана."
    assert fake_session.last(ADMIN_ID).reply_markup is not None


async def test_more_menu(app: Any, fake_session: Any) -> None:
    """«Ещё»: Другой день, Записи, Выходной, Настройки и у администратора — Админ (1.0.2: «Текстом» убрана); старая
    кнопка «Текстом» без ключа модели — «пока не подключён»."""
    chat = await _chat(app, fake_session)
    assert await chat.say("☰ Ещё") == MORE_TITLE
    assert _labels(fake_session.last(ADMIN_ID).reply_markup) == [
        ["📅 Другой день", "📋 Записи"], ["🛌 Выходной", "⚙️ Настройки"], ["🛠 Админ"],
    ]
    user_id = await chat.user_id()
    await chat.press(MenuCb(o=user_id, t=0, k="text").pack())
    assert fake_session.last(ADMIN_ID).text == "Разбор текстом пока не подключён. Кнопки работают как обычно"


async def test_ready_section_is_left_to_its_module(app: Any, fake_session: Any) -> None:
    """Когда модуль подключил раздел, ядро не отвечает за него «скоро»."""
    app.telegram.menu.add(FUTURE)
    chat = await _chat(app, fake_session)
    app.telegram.menu.mark_ready("future")
    assert await chat.say("🔮 Новое") == NOT_UNDERSTOOD


async def test_input_check_full_flow(app: Any, fake_session: Any) -> None:
    """Раздел 9 «Понятные ошибки»: ошибки ввода не сбрасывают диалог; «177,5», «5.45», «вчера» понимаются."""
    chat = await _chat(app, fake_session)
    assert await chat.say("/check") == STEP_HEIGHT
    assert await chat.say("1780") == "Рост — от 120 до 230 см. Вы ввели 1780 — может, лишняя цифра?"
    assert await chat.say("4,5,1") == "Не понял число „4,5,1“. Напишите, например, 4,5 или 4.5"
    assert await chat.say("177,5") == STEP_TIME
    assert await chat.say("5:75") == "Время пишите как 5:45, 5.45 или в секундах: 345"
    assert await chat.say("5.45") == STEP_DATE
    # Часы теста: 03.11.2026 15:00 по Москве — логический сегодняшний день 03.11.
    assert await chat.say("04.11") == "Нельзя записать на 04.11 — это будущее. Сегодня 03.11"
    assert await chat.say("31.02") == "Дату пишите как 20.10 или 20.10.2026"
    summary = await chat.say("вчера")
    assert "рост 177,5 см" in summary
    assert "время 5:45 (345 сек)" in summary
    assert "дата 02.11.2026" in summary
    token = await chat.token()
    await chat.press(StepCb(o=await chat.user_id(), t=token, a="done").pack())
    assert chat.texts()[-1] == FINISHED
    assert await chat.states() == []
    assert fake_session.markup_removals()


async def test_cancel_word_command_and_button(app: Any, fake_session: Any) -> None:
    """Раздел 3 «Отмена»: кнопка «✕ Отмена», слово «отмена» и /cancel закрывают ввод, ничего не записывая."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    assert await chat.say("  Отмена ") == CANCELLED
    assert await chat.states() == []
    assert await chat.say("/cancel") == NOTHING_TO_CANCEL
    await chat.say("/check")
    await chat.say("178")
    await chat.press(CancelCb(o=await chat.user_id(), t=await chat.token()).pack())
    assert chat.texts()[-1] == CANCELLED
    assert await chat.states() == []


async def test_menu_button_closes_unfinished_input(app: Any, fake_session: Any) -> None:
    """Переход в раздел меню посреди ввода закрывает ввод: «📊 Итоги» не принимается за число."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    await chat.say("📊 Итоги")
    assert len(fake_session.photos(ADMIN_ID)) == 1  # открылись итоги
    assert await chat.states() == []


async def test_reset_after_15_minutes_is_silent_and_buttons_go_stale(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: 15 минут без действий — ввод сброшен, бот ничего не прислал; старая кнопка — «Это меню устарело»."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    await chat.say("178")
    user_id, token = await chat.user_id(), await chat.token()
    sent_before = len(chat.texts())
    clock.advance(minutes=15)
    assert await app.telegram.expire_idle() == 1
    assert len(chat.texts()) == sent_before
    assert await chat.states() == []
    await chat.press(CancelCb(o=user_id, t=token).pack())
    assert chat.texts()[-1] == STALE
    assert fake_session.last(ADMIN_ID).reply_markup is not None


async def test_reset_checked_on_next_action(app: Any, fake_session: Any, clock: Any) -> None:
    """Сброс проверяется и при следующем действии: через 16 минут число уже не ждётся."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    clock.advance(minutes=16)
    assert await chat.say("178") == NOT_UNDERSTOOD
    assert await chat.states() == []


async def test_activity_extends_input(app: Any, fake_session: Any, clock: Any) -> None:
    """Таймер считается от последнего сообщения или нажатия: 14 + 14 минут с ответом между ними — ввод жив."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    clock.advance(minutes=14)
    assert await chat.say("178") == STEP_TIME
    clock.advance(minutes=14)
    assert await app.telegram.expire_idle() == 0
    assert await chat.say("5:45") == STEP_DATE


async def test_reset_after_restart(settings: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: сброс срабатывает и после перезапуска бота."""
    first = build_app(settings, telegram_session=fake_session, clock=clock)
    await first.startup()
    chat = await _chat(first, fake_session)
    await chat.say("/check")
    await first.close()

    clock.advance(minutes=20)
    second = build_app(settings, telegram_session=fake_session, clock=clock)
    await second.startup()  # задача сброса выполняется сразу при старте
    try:
        assert await Chat(second, fake_session).states() == []
    finally:
        await second.close()


async def test_new_dialog_makes_old_buttons_stale(app: Any, fake_session: Any) -> None:
    """Повторный /check начинает ввод заново: кнопки прошлого ввода устаревают."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    old = await chat.token()
    await chat.say("/check")
    assert await chat.token() != old
    await chat.press(CancelCb(o=await chat.user_id(), t=old).pack())
    assert chat.texts()[-1] == STALE
    assert len(await chat.states()) == 1


async def test_foreign_callback_refused(app: Any, fake_session: Any) -> None:
    """Раздел 9 «Изоляция»: подменённый callback получает отказ, ввод не меняется."""
    chat = await _chat(app, fake_session)
    await chat.say("/check")
    user_id, token = await chat.user_id(), await chat.token()
    await chat.press(CancelCb(o=user_id + 1, t=token).pack())
    assert chat.texts()[-1] == FOREIGN
    assert len(await chat.states()) == 1
    await chat.press(MenuCb(o=user_id + 1, t=0, k="settings").pack())
    assert chat.texts()[-1] == FOREIGN


async def test_unknown_button_is_stale(app: Any, fake_session: Any) -> None:
    """Кнопка из старой версии бота или с мусорными данными — «Это меню устарело» и главное меню."""
    chat = await _chat(app, fake_session)
    await chat.press("что-то старое")
    assert chat.texts()[-1] == STALE
