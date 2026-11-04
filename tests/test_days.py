"""Часть 4, раздел 3.7 и критерии раздела 9 «Дата записи и прошедшие дни»: граница 04:00, «Другой день»,
выходной, перенос «📅 На вчера», карточка дня, настройка главного экрана."""

from datetime import UTC, date, datetime
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from habit_bot.app import build_app
from habit_bot.channels.telegram.dialogs.fsm import start_dialog
from habit_bot.channels.telegram.dialogs.policy import LOST_DAY, OTHER_DAY
from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.channels.telegram.ui.menu import MenuEntry
from habit_bot.kernel.errors import AppError
from habit_bot.modules.days.telegram.handlers import MoveCb, move_button
from tests.conftest import ADMIN_ID, OTHER_ID, register_active
from tests.fakes import TgChat

MSK_0020 = datetime(2026, 10, 24, 21, 20, tzinfo=UTC)  # 25.10 00:20 по Москве
MSK_DAY = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)    # 25.10 15:00 по Москве


async def _chat(app: Any, fake_session: Any, clock: Any, now: datetime = MSK_DAY) -> tuple[TgChat, Any]:
    clock.current = now
    actor = await register_active(app)
    return TgChat(app, fake_session, ADMIN_ID), actor


async def _menu(chat: TgChat, actor: Any, key: str) -> str:
    await chat.press_data(MenuCb(o=actor.user_id, t=0, k=key).pack())
    return chat.texts()[-1]


async def test_day_boundary(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: запись 25.10 в 00:20 попадает в 24.10; в 04:05 — в 25.10."""
    chat, actor = await _chat(app, fake_session, clock, MSK_0020)
    assert (await _menu(chat, actor, "day_off")).startswith("🛌 24.10 — выходной")
    clock.current = datetime(2026, 10, 25, 1, 5, tzinfo=UTC)  # 04:05
    assert (await _menu(chat, actor, "day_off")).startswith("🛌 25.10 — выходной")


async def test_input_started_before_boundary(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> None:
    """Раздел 9: ввод с 03:58 по 04:02 — в 24.10 (дата берётся по началу ввода)."""

    class Probe(StatesGroup):
        waiting = State()

    router = Router(name="probe")

    @router.message(Command("probe"))
    async def begin(message: Message, state: FSMContext, record_day: date) -> None:
        await start_dialog(state, Probe.waiting, record_day)
        await message.answer("начал")

    @router.message(F.text == "конец")
    async def finish(message: Message, record_day: date) -> None:
        await message.answer(f"записано в {record_day:%d.%m}")

    app = build_app(settings, telegram_session=fake_session, clock=clock, geocoder=geocoder)
    app.telegram.add_router(router)
    await app.startup()
    try:
        clock.current = datetime(2026, 10, 25, 0, 58, tzinfo=UTC)  # 03:58
        await register_active(app)
        chat = TgChat(app, fake_session, ADMIN_ID)
        await chat.say("/probe")
        clock.current = datetime(2026, 10, 25, 1, 2, tzinfo=UTC)  # 04:02
        assert await chat.say("конец") == "записано в 24.10"
    finally:
        await app.close()


async def test_quick_days_at_2am(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: 25.10 в 02:00 кнопка «Вчера» показывает «Вчера (23.10)» — логический сегодня 24.10."""
    chat, actor = await _chat(app, fake_session, clock, datetime(2026, 10, 24, 23, 0, tzinfo=UTC))
    await _menu(chat, actor, "other_day")
    assert chat.labels()[:3] == ["Вчера (23.10)", "Позавчера (22.10)", "Ср (21.10)"]


async def test_other_day_mode_and_return(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: «Вчера» → режим, первая кнопка «📅 24.10 ✕ Вернуться к сегодня»; выходной — за выбранный день."""
    chat, actor = await _chat(app, fake_session, clock)
    assert (await _menu(chat, actor, "other_day")).startswith("За какой день записать?")
    text = await chat.press("Вчера (24.10)")
    assert text.startswith("Записываю за 24.10. Всё, что добавите, попадёт в этот день.\n<pre>24.10, сб")
    assert "Цель: 2 800 ккал · Б 160 · Ж 80 · У 360" in text
    assert chat.keyboard()[0] == ["📅 24.10 ✕ Вернуться к сегодня"]
    assert (await _menu(chat, actor, "day_off")).startswith("🛌 24.10 — выходной")
    assert "24.10, сб · 🛌 выходной" in chat.texts()[-1]
    assert await chat.say("📅 24.10 ✕ Вернуться к сегодня") == "Вернулись к сегодняшнему дню (25.10)."
    assert chat.keyboard()[0] == ["🍽 Еда", "🤸 Зарядка"]
    assert await app.telegram.dialogs.day(actor.user_id, OTHER_DAY) is None
    days = app.ctx.services["days"]
    assert await days.is_day_off(actor, date(2026, 10, 24))
    assert (await _menu(chat, actor, "day_off")).startswith("🛌 25.10")
    assert (await _menu(chat, actor, "day_off")).startswith("Отметка «Выходной» за 25.10 снята.")
    assert (await _menu(chat, actor, "day_off")).startswith("🛌 25.10")


async def test_cancel_on_every_step(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: «✕ Отмена» на экране выбора даты и в календаре — режим не включается, записей нет."""
    chat, actor = await _chat(app, fake_session, clock)
    await _menu(chat, actor, "other_day")
    assert await chat.press("✕ Отмена") == "Отменено, ничего не записано."
    await _menu(chat, actor, "other_day")
    await chat.press("🗓 Выбрать дату")
    assert chat.find_button("Октябрь 2026")
    assert await chat.press("✕ Отмена") == "Отменено, ничего не записано."
    assert await app.telegram.dialogs.day(actor.user_id, OTHER_DAY) is None
    await _menu(chat, actor, "other_day")
    await chat.press("Вчера (24.10)")
    assert await chat.say("отмена") == "Отменено, ничего не записано. Вернулись к сегодняшнему дню."


async def test_calendar_future_and_old_dates(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: будущую дату выбрать нельзя; дата старше 30 дней требует подтверждения."""
    chat, actor = await _chat(app, fake_session, clock)
    await _menu(chat, actor, "other_day")
    assert await chat.say("27.10") == "Нельзя записать на 27.10 — это будущее. Сегодня 25.10"
    assert await chat.say("25.10") == "Это сегодняшний день — записи и так попадают в него."
    await _menu(chat, actor, "other_day")
    await chat.press("🗓 Выбрать дату")
    calendar = [b.text for m in fake_session.edits() if m.reply_markup for row in m.reply_markup.inline_keyboard
                for b in row]
    assert "26" not in calendar and "·" in calendar and "25" in calendar
    await chat.press("◀")
    assert (await chat.press("20")) == "Это 35 дней назад (20.09), всё верно?"
    assert (await chat.press("Да")).startswith("Записываю за 20.09.")


async def test_unsaved_input_on_return(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: в режиме посреди ввода «Вернуться к сегодня» → «Выйти без сохранения?» → «Да»: ввод не сохранён."""
    chat, actor = await _chat(app, fake_session, clock)
    await _menu(chat, actor, "other_day")
    await chat.press("Позавчера (23.10)")
    await chat.say("/check")
    assert await chat.say("📅 23.10 ✕ Вернуться к сегодня") == "Ввод не сохранён. Выйти без сохранения?"
    await chat.press("Продолжить ввод")
    assert await app.telegram.dialogs.get(actor.user_id, "dialog") is not None
    await chat.say("📅 23.10 ✕ Вернуться к сегодня")
    assert await chat.press("Да") == "Вернулись к сегодняшнему дню (25.10)."
    assert await app.telegram.dialogs.get(actor.user_id, "dialog") is None
    assert await app.telegram.dialogs.day(actor.user_id, OTHER_DAY) is None


async def test_mode_resets_after_15_minutes(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 3: через 15 минут режим выключен молча; остаётся отметка для «📅 Нет, за 24.10»."""
    chat, actor = await _chat(app, fake_session, clock)
    await _menu(chat, actor, "other_day")
    await chat.press("Вчера (24.10)")
    sent = len(chat.texts())
    clock.advance(minutes=15)
    assert await app.telegram.expire_idle() == 1
    assert len(chat.texts()) == sent
    assert await app.telegram.dialogs.day(actor.user_id, LOST_DAY) == date(2026, 10, 24)
    assert await chat.say("📅 24.10 ✕ Вернуться к сегодня") == "Вы и так в сегодняшнем дне."
    clock.advance(hours=13)
    await app.telegram.expire_idle()
    assert await app.telegram.dialogs.day(actor.user_id, LOST_DAY) is None


class FakeMover:
    def __init__(self, owner: int) -> None:
        self.owner = owner
        self.entries = {"e1": date(2026, 10, 25)}

    async def day_of(self, actor: Any, public_id: str) -> date | None:
        return self.entries.get(public_id) if actor.user_id == self.owner else None

    async def move(self, actor: Any, public_id: str, day: date) -> None:
        self.entries[public_id] = day


async def test_move_to_yesterday(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: «📅 На вчера» переносит запись, итоги обоих дней; кнопка работает через час, но не через сутки."""
    chat, actor = await _chat(app, fake_session, clock)
    days = app.ctx.services["days"]
    mover = FakeMover(actor.user_id)
    days.add_mover("x", mover)
    days.add_card_section(lambda a, d: _section(d))
    minute = int(clock.now().timestamp() // 60)
    data = move_button(actor, "x", "e1", minute).callback_data
    clock.advance(hours=1)
    await chat.press_data(data)
    assert mover.entries["e1"] == date(2026, 10, 24)
    assert fake_session.answers()[-1].text == "Перенесено на 24.10"
    assert chat.texts()[-2].startswith("Итоги 24.10:\n<pre>24.10, сб")
    assert "🍽 запись за 24.10" in chat.texts()[-2]
    assert chat.texts()[-1].startswith("Итоги 25.10:")

    await chat.press_data(MoveCb(o=actor.user_id, t=0, k="x", i="нет-такой", m=minute).pack())
    assert chat.texts()[-1] == "Это меню устарело. Вот главное меню 👇"
    clock.advance(hours=24)
    await chat.press_data(data)
    assert chat.texts()[-1] == "Это меню устарело. Вот главное меню 👇"
    assert mover.entries["e1"] == date(2026, 10, 24)
    assert await days.move(actor, "нет-вида", "e1") is None


async def _section(day: date) -> list[str]:
    return [f"🍽 запись за {day:%d.%m}"]


async def test_day_off_not_in_future_and_isolation(app: Any, clock: Any) -> None:
    """Выходной нельзя поставить на будущее; выходные одного пользователя не видны другому."""
    clock.current = MSK_DAY
    admin = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(admin, max_uses=1, days=1)
    guest = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    days = app.ctx.services["days"]
    try:
        await days.toggle_day_off(admin, date(2026, 10, 26))
        raise AssertionError("будущее")
    except AppError as err:
        assert err.code == "INPUT-FUTURE"
    await days.toggle_day_off(admin, date(2026, 10, 24))
    assert await days.days_off(guest, date(2026, 10, 1), date(2026, 10, 31)) == set()
    assert await days.days_off(admin, date(2026, 10, 1), date(2026, 10, 31)) == {date(2026, 10, 24)}


async def test_home_screen_settings(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 3.1: главный экран настраивается — скрыть «Тренировку», поднять «Привычки»; «Ещё» скрыть нельзя."""
    chat, actor = await _chat(app, fake_session, clock)
    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    assert (await chat.press("🏠 Главный экран")).startswith("🏠 Главный экран")
    await chat.press("☑ 🏋️ Тренировка")
    await chat.press("⬆")  # первая «⬆» — у «🤸 Зарядки»: она встаёт первой
    await chat.press("✅ Готово")
    assert chat.texts()[-1] == "Главный экран сохранён 👇"
    assert chat.keyboard() == [["🤸 Зарядка", "🍽 Еда"], ["✅ Привычки", "📊 Итоги"], ["☰ Ещё"]]
    assert await app.ctx.services["users.profiles"].home_layout(actor) == ["warmup", "food", "habits", "stats"]

    for i in range(5):
        app.telegram.menu.add(MenuEntry(f"h{i}", f"Привычка {i}", 100 + i))
    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    await chat.press("🏠 Главный экран")
    for i in range(4):
        await chat.press(f"☐ Привычка {i}")
    assert fake_session.answers()[-1].text == "Не больше 7 кнопок — плюс «☰ Ещё»"
    await chat.press("↩ По умолчанию")
    await chat.press("✅ Готово")
    assert await app.ctx.services["users.profiles"].home_layout(actor) is None
