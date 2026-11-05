"""Раскладка кнопок по ширине и чистый чат (след сообщений) — по отдельности, без сценариев."""

from typing import Any

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import DeleteMessages
from aiogram.types import InlineKeyboardButton, KeyboardButton, ReplyKeyboardMarkup, Update

from habit_bot.channels.telegram.dialogs.policy import TRAIL, InactivityPolicy
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.layout import budget, fit_rows, fits, inline, label_width, reflow, row_problem
from habit_bot.channels.telegram.ui.menu import HOME_LABEL, MenuEntry, MenuRegistry, Place
from habit_bot.kernel.identity import Actor, Role
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import callback_update, message_update


def _button(text: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data="x")


def test_label_width() -> None:
    assert label_width("Отжимания") == 9
    assert label_width("🏋️ Тренировка") == 12.5  # эмодзи 2, селектор 0, пробел 0,5
    assert label_width("Вчера (24.10)") == pytest.approx(5 + 0.5 + 0.5 + 4 * 0.85 + 0.5 + 0.5)
    assert label_width("☰ Ещё") == 5.5


def test_fits_and_budgets() -> None:
    assert fits(["Очень-очень длинное название рецепта, которое не влезет никуда"])  # одной кнопке шире некуда
    assert fits(["🏋️ Тренировка", "✅ Привычки"])
    assert not fits(["−", "Отжимания 50", "+"])  # жалоба владельца: в ряду из трёх обрезалось
    assert fits(["✏️ Шаг", "⬆ Выше", "✕ Убрать"])
    assert budget(9) == 1.0  # больше 8 в ряд не бывает — помещается разве что одна буква
    assert row_problem(["×0,5", "×2"]) is None
    problem = row_problem(["×0,5", "×2", "Отменить", "📅 На вчера"])
    assert problem is not None and "«📅 На вчера»" in problem and "ряд из 4" in problem


def test_fit_rows_and_reflow() -> None:
    labels = ["Овсянка", "Омлет", "Салат с тунцом и авокадо", "Чай", "Кофе"]
    assert [[b.text for b in row] for row in fit_rows([_button(t) for t in labels])] == [
        ["Овсянка", "Омлет"], ["Салат с тунцом и авокадо"], ["Чай", "Кофе"]]
    assert fit_rows(["×0,5", "×2", "Отменить", "📅 На вчера"]) == [["×0,5", "×2"], ["Отменить", "📅 На вчера"]]
    assert fit_rows(["1", "2", "3"], max_cols=3) == [["1", "2", "3"]]
    assert fit_rows([]) == []
    assert reflow([[], ["Новичок", "Средний", "Продвинутый"], ["1", "2"]]) == [
        ["Новичок", "Средний"], ["Продвинутый"], ["1", "2"]]
    markup = inline([[_button("−"), _button("Отжимания 50"), _button("+")]])
    assert [[b.text for b in row] for row in markup.inline_keyboard] == [["−", "Отжимания 50"], ["+"]]


def _actor(admin: bool = True) -> Actor:
    from datetime import UTC, datetime
    return Actor(user_id=1, role=Role.ADMIN if admin else Role.USER, channel="telegram",
                 request_time=datetime(2026, 11, 3, tzinfo=UTC))


def test_home_keyboard_rows_and_hidden_in_more() -> None:
    menu = MenuRegistry()
    actor = _actor()
    rows = [[b.text for b in row] for row in menu.home_keyboard(actor, ["food", "warmup"]).keyboard]
    assert rows == [["🍽 Еда", "🤸 Зарядка"], [HOME_LABEL, "☰ Ещё"]]
    rows = [[b.text for b in row] for row in menu.home_keyboard(actor, ["food", "workout", "stats"]).keyboard]
    assert rows == [["🍽 Еда", "🏋️ Тренировка"], ["📊 Итоги", HOME_LABEL, "☰ Ещё"]]  # короткая встаёт третьей
    rows = [[b.text for b in row] for row in menu.home_keyboard(actor, ["food", "workout"]).keyboard]
    assert rows[-1] == [HOME_LABEL, "☰ Ещё"]
    rows = [[b.text for b in row] for row in menu.home_keyboard(actor, ["workout"]).keyboard]
    assert rows == [["🏋️ Тренировка"], [HOME_LABEL, "☰ Ещё"]]  # «Тренировка» третьей не помещается
    assert [e.key for e in menu.hidden(actor, ["food", "stats"])] == ["warmup", "workout", "habits"]
    assert menu.hidden(actor, None) == []
    more = [b.text for row in menu.more_keyboard(actor, ["food"]).inline_keyboard for b in row]
    assert more[:4] == ["🤸 Зарядка", "🏋️ Тренировка", "✅ Привычки", "📊 Итоги"]
    assert more[4:] == ["📅 Другой день", "✍️ Текстом", "🛌 Выходной", "⚙️ Настройки", "🛠 Админ"]
    menu.add(MenuEntry("h1", "Очень длинная своя привычка", 100))
    assert ["Очень длинная своя привычка"] in [
        [b.text for b in row] for row in menu.more_keyboard(_actor(False), ["food"]).inline_keyboard]
    assert MenuEntry("x", "x", 1).place is Place.HOME


def test_trail_scope_lives_48_hours() -> None:
    assert InactivityPolicy().ttl_for(TRAIL).total_seconds() == 48 * 3600


def test_trail_calls_outside_update_do_nothing() -> None:
    trail.result()
    trail.clean()
    trail.forget()
    trail.discard(5)
    trail.keep(5)
    trail.discard(None)


class _Env:
    def __init__(self, app: Any, fake_session: Any, user_id: int) -> None:
        self.app = app
        self.session = fake_session
        self.bot = app.telegram.bot
        self.store = app.telegram.dialogs
        self.user_id = user_id
        self.middleware = trail.TrailMiddleware(self.store, app.ctx.clock)
        self.next = 1000

    async def run(self, step: Any, *, text: str | None = "x", actor: bool = True, chat_type: str = "private") -> int:
        """Один апдейт: сообщение пользователя (или нажатие, если text=None) и обработчик ``step``."""
        self.next += 1
        raw = message_update(self.next, ADMIN_ID, text) if text is not None else callback_update(self.next, ADMIN_ID,
                                                                                                    "x")
        if text is not None:
            raw["message"]["chat"]["type"] = chat_type
        update = Update.model_validate(raw, context={"bot": self.bot})
        data = {"bot": self.bot, **({"actor": type("A", (), {"user_id": self.user_id})()} if actor else {})}

        async def handler(event: Any, data: dict[str, Any]) -> Any:
            await step()
            return "ok"

        assert await self.middleware(handler, update, data) == "ok"
        return self.next

    async def send(self, chat_id: int = ADMIN_ID, keyboard: bool = False) -> int:
        markup = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="☰ Ещё")]]) if keyboard else None
        return (await self.bot.send_message(chat_id, "текст", reply_markup=markup)).message_id

    async def saved(self) -> dict[str, Any]:
        snapshot = await self.store.get(self.user_id, TRAIL)
        return snapshot.data if snapshot else {}


@pytest.fixture
async def env(app: Any, fake_session: Any) -> _Env:
    actor = await app.ctx.services["users.sign_in"].execute(ADMIN_ID, "Егор")
    return _Env(app, fake_session, actor.user_id)


async def test_trail_result_keeps_result_and_keyboard(env: _Env) -> None:
    sent: dict[str, int] = {}

    async def ask() -> None:
        sent["kb"] = await env.send(keyboard=True)
        sent["question"] = await env.send()
        sent["admin"] = await env.send(OTHER_ID)  # оповещение другому человеку — не след

    typed = await env.run(ask)
    assert sorted((await env.saved())["ids"]) == sorted([typed, sent["question"]])
    assert (await env.saved())["kb"] == sent["kb"]

    async def answer() -> None:
        trail.result()
        sent["card"] = await env.send()

    answered = await env.run(answer)
    deleted = env.session.deleted
    assert {(ADMIN_ID, typed), (ADMIN_ID, sent["question"]), (ADMIN_ID, answered)} <= deleted
    assert (ADMIN_ID, sent["card"]) not in deleted and (ADMIN_ID, sent["kb"]) not in deleted
    assert (OTHER_ID, sent["admin"]) not in deleted
    assert await env.saved() == {"ids": [], "kb": sent["kb"]}


async def test_trail_keyboard_holder_moves_and_result_keyboard_stays(env: _Env) -> None:
    ids: dict[str, int] = {}

    async def first() -> None:
        ids["kb1"] = await env.send(keyboard=True)

    async def second() -> None:
        ids["kb2"] = await env.send(keyboard=True)

    await env.run(first)
    await env.run(second)
    assert ids["kb1"] in (await env.saved())["ids"] and (await env.saved())["kb"] == ids["kb2"]

    async def result_with_keyboard() -> None:
        trail.result()
        ids["kb3"] = await env.send(keyboard=True)  # «Готово, …» с клавиатурой — итог навсегда

    await env.run(result_with_keyboard)
    assert (ADMIN_ID, ids["kb1"]) in env.session.deleted and (ADMIN_ID, ids["kb2"]) in env.session.deleted
    assert (ADMIN_ID, ids["kb3"]) not in env.session.deleted
    assert await env.saved() == {}


async def test_trail_clean_discard_keep_forget(env: _Env) -> None:
    ids: dict[str, int] = {}

    async def draft() -> None:
        ids["draft"] = await env.send()
        ids["note"] = await env.send()

    await env.run(draft, text=None)

    async def replace_draft() -> None:
        trail.discard(ids["draft"])
        ids["draft2"] = await env.send()

    await env.run(replace_draft, text=None)
    assert (ADMIN_ID, ids["draft"]) in env.session.deleted and (ADMIN_ID, ids["note"]) not in env.session.deleted

    async def edit_into_result() -> None:
        trail.keep(ids["draft2"])  # текст черновика заменили итогом

    await env.run(edit_into_result, text=None)
    assert (ADMIN_ID, ids["note"]) in env.session.deleted and (ADMIN_ID, ids["draft2"]) not in env.session.deleted

    async def home() -> None:
        trail.clean()

    async def chatter() -> None:
        ids["hint"] = await env.send()

    await env.run(chatter)
    pressed = await env.run(home)
    assert (ADMIN_ID, ids["hint"]) in env.session.deleted and (ADMIN_ID, pressed) in env.session.deleted

    async def gone() -> None:
        trail.forget()
        await env.send()

    await env.run(gone)
    assert await env.saved() == {}


async def test_trail_skips_foreign_updates_and_survives_errors(env: _Env, monkeypatch: Any) -> None:
    async def nothing() -> None:
        await env.send()

    await env.run(nothing, actor=False)  # незнакомец: следа нет
    await env.run(nothing, chat_type="group")  # не личный чат: следа нет
    assert await env.saved() == {}
    assert await env.middleware(lambda e, d: _async("passed"), object(), {}) == "passed"  # type: ignore[arg-type]
    empty = Update.model_validate({"update_id": 1, "edited_message": message_update(1, ADMIN_ID, "x")["message"]})
    assert await env.middleware(lambda e, d: _async("edit"), empty, {}) == "edit"

    async def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(env.store, "get", broken)
    await env.run(nothing)  # ответ пользователю не ломается


async def _async(value: str) -> str:
    return value


async def test_delete_all_in_chunks_and_ignores_telegram_refusal(env: _Env, monkeypatch: Any) -> None:
    await trail.delete_all(env.bot, ADMIN_ID, [*range(1, 251), 5, 5])
    calls = [m for m in env.session.requests if isinstance(m, DeleteMessages)]
    assert [len(m.message_ids) for m in calls] == [100, 100, 50]

    async def refuse(*args: Any, **kwargs: Any) -> Any:
        raise TelegramBadRequest(method=calls[0], message="Bad Request: message can't be deleted for everyone")

    monkeypatch.setattr(env.bot, "delete_messages", refuse)
    await trail.delete_all(env.bot, ADMIN_ID, [1, 2])


async def test_trail_is_capped(env: _Env, monkeypatch: Any) -> None:
    monkeypatch.setattr(trail, "TRAIL_LIMIT", 3)

    async def many() -> None:
        for _ in range(5):
            await env.send()

    await env.run(many, text=None)
    assert len((await env.saved())["ids"]) == 3
