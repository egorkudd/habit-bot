"""Поведенческие сценарии: «⚙️ Настройки» → «📥 Импорт» (правки 1.0.3) — готовые действия без модели (сообщением или
файлом) и длинное заполнение с ИИ частями."""

import json
from collections.abc import AsyncIterator
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from habit_bot.kernel.errors import AppError
from tests.conftest import ADMIN_ID
from tests.fakes import FakeLlm
from tests.scenarios.conftest import pass_onboarding
from tests.scenarios.harness import Persona, World

TODAY, YESTERDAY = date(2026, 11, 3), date(2026, 11, 2)
STALE = "Это меню устарело. Вот главное меню 👇"


async def _actor(world: World) -> Any:
    return await world.service("users.sign_in").execute(ADMIN_ID, "")


async def _start_import(owner: Persona) -> str:
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    assert (await owner.tap("📥 Импорт")).startswith("📥 Импорт данных. Как загрузить?")
    return await owner.tap("📋 Готовые действия")


def _history() -> list[dict[str, Any]]:
    return [
        {"type": "food.add", "day": "2026-11-01", "item": "Каша", "kcal": 400, "protein": 15, "fat": 10,
         "carbs": 60, "price": 80},
        {"type": "habit.mark", "day": "2026-11-01", "habit": "Глаза", "times": 3},
        {"type": "run.add", "day": "2026-11-02", "distance_km": 5.2, "time": "28:40"},
        {"type": "weight.record", "day": "2026-11-01", "kg": 75.4},
        {"type": "workout.set", "day": "2026-11-02", "exercise": "Присед со штангой", "weight": 100,
         "reps": [8, 8, 8]},
        {"type": "warmup.add", "day": "2026-11-02", "values": {"Отжимания": "50"}},
        {"type": "day.off", "day": "2026-10-31"},
    ]


async def test_s147_import_ready_actions_message(world: World, owner: Persona) -> None:
    """S-147. «📥 Импорт» → «📋 Готовые действия» → JSON сообщением: еда, отметки привычки, бег, вес за прошлый
    день, тренировка, зарядка, выходной — карточка «Понял так» группами без «✏️ Исправить» (это для модели);
    «✅ Выполнить всё» — всё записано за свои дни, вес профиля не изменился; «↩️ Отменить всё» — как было.
    Модель не нужна: ключа нет."""
    actor = await _actor(world)
    await world.service("habits").from_template(actor, "eyes")
    await world.service("warmup").use_default_set(actor)
    assert (await _start_import(owner)).startswith("📋 Пришлите готовые действия в JSON")
    card = await owner.say(json.dumps({"actions": _history()}, ensure_ascii=False))
    assert card.startswith("Понял так:\nЕда: 1 · Привычки: 1 · Бег: 1 · Вес: 1 · Тренировки: 1 · Зарядка: 1 · Дни: 1")
    assert "✏️ Исправить" not in owner.labels() and "✅ Выполнить всё" in owner.labels()
    profile_weight = (await world.service("users.profiles").profile(actor)).weight_kg
    done = await owner.tap("✅ Выполнить всё")
    assert done.startswith("Готово:\n1.")
    assert [e.name for e in await world.service("food").entries(actor, date(2026, 11, 1))] == ["Каша"]
    weights = await world.service("users.profiles").weights_between(actor, date(2026, 11, 1), YESTERDAY)
    assert weights == {date(2026, 11, 1): Decimal("75.4")}
    assert (await world.service("users.profiles").profile(actor)).weight_kg == profile_weight
    assert len(await world.service("workouts").day_sessions(actor, YESTERDAY)) == 1
    assert len(await world.service("days").entries(actor, YESTERDAY)) == 3  # тренировка, бег, зарядка
    assert await owner.tap("↩️ Отменить всё") == "↩️ Отменено, данные как было (действий: 7)."
    assert await world.service("food").entries(actor, date(2026, 11, 1)) == []
    assert await world.service("users.profiles").weights_between(actor, date(2026, 11, 1), YESTERDAY) == {}
    assert await world.service("days").entries(actor, YESTERDAY) == []


async def test_s148_import_errors_file_and_list(world: World, owner: Persona) -> None:
    """S-148. Не JSON — «Не смог прочитать действия…», ввод остаётся; пустой список — та же подсказка; список без
    обёртки «actions» тоже подходит; будущая дата и чужая привычка — «Не выполню», непонятное действие — «Не по
    формату: 1»; файл .json — то же, что сообщение; файл не в UTF-8 — подсказка; «🏠 Домой» выходит из ввода."""
    actor = await _actor(world)
    await world.service("habits").from_template(actor, "eyes")
    await _start_import(owner)
    assert await owner.say("съел кашу") == (
        "Не смог прочитать действия: не JSON — нужен список действий в JSON. Ничего не изменено")
    assert (await owner.say("[]")).startswith("Не смог прочитать действия: ни одно действие не подошло")
    card = await owner.say(json.dumps([
        {"type": "habit.mark", "day": "2026-11-02", "habit": "Глаза"},
        {"type": "habit.mark", "day": "2026-12-01", "habit": "Глаза"},
        {"type": "habit.mark", "day": "2026-11-02", "habit": "Йога"},
        {"type": "teleport", "day": "2026-11-02"},
    ], ensure_ascii=False))
    assert card.startswith("Понял так:\nПривычки: 1\n1. ")
    assert "Не выполню:" in card and "Не по формату: 1" in card
    await owner.tap("✕ Отмена")
    await _start_import(owner)
    assert (await owner.send_document("bad.txt", b"\xff\xfe\x00")).startswith(
        "Не смог прочитать действия: файл не текстовый")
    payload = json.dumps({"actions": [{"type": "habit.mark", "day": "2026-11-01", "habit": "Глаза",
                                       "times": 2}]}, ensure_ascii=False).encode()
    assert (await owner.send_document("history.json", payload)).startswith("Понял так:\nПривычки: 1")
    await owner.tap("✅ Выполнить всё")
    assert (await world.service("habits").day(actor, date(2026, 11, 1)))[0].fact == 2
    await _start_import(owner)
    await owner.tap("🏠 Домой")
    assert await owner.say("[]") == "Не понял. Выберите раздел в меню 👇"


async def test_s149_import_big_file_and_ai_without_key(world: World, owner: Persona) -> None:
    """S-149. Файл больше 200 КБ — «разбейте на части», ничего не записано; 300 действий файлом — карточка
    страницами по 10, «✅ Выполнить всё» записывает все 300 (больше, чем 50 у модели); «🤖 С ИИ» без ключа модели —
    «пока не подключён»."""
    actor = await _actor(world)
    await world.service("habits").from_template(actor, "eyes")
    await _start_import(owner)
    assert "разбейте на части" in await owner.send_document("big.json", b" " * 200_001)
    actions = [{"type": "habit.mark", "day": f"2026-{(i % 9) + 1:02d}-{(i % 28) + 1:02d}", "habit": "Глаза"}
               for i in range(300)]
    card = await owner.send_document("year.json", json.dumps(actions, ensure_ascii=False).encode())
    assert card.startswith("Понял так:\nПривычки: 300\nСтраница 1 из 30")
    await owner.tap("✅ Выполнить всё")
    marks = await world.service("habits").entries_between(actor, date(2026, 1, 1), TODAY)
    assert len(marks) == 300
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("📥 Импорт")
    assert await owner.tap("🤖 С ИИ") == "Разбор текстом пока не подключён. Кнопки работают как обычно"


@pytest.fixture
async def long_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    """Модель отвечает на каждую часть длинного текста своими действиями: по 40 отметок на часть."""
    llm = FakeLlm({f"Часть {n}:": {"actions": [
        {"type": "habit.mark", "day": f"2026-10-{d:02d}", "habit": "Глаза"} for d in range(1, 21)] * 2}
        for n in (1, 2, 3)})
    w = await World(settings, fake_session, clock, geocoder, llm=llm).start()
    yield w
    await w.stop()


async def test_s150_ai_fill_long_text_in_parts(long_world: World) -> None:
    """S-150. «🤖 С ИИ»: текст 3 900 знаков — модель разбирает его тремя частями (ответ на каждую — свой, длинный
    список не обрывается), в карточке 120 отметок (больше 50) страницами; после «✅ Выполнить всё» — все 120."""
    owner = long_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(owner)
    actor = await _actor(long_world)
    await long_world.service("habits").from_template(actor, "eyes")
    text = "\n".join(f"Часть {n}: " + "глаза делал каждый день " * 60 for n in (1, 2, 3))[:3900]
    await owner.tap("☰ Ещё")
    await owner.tap("⚙️ Настройки")
    await owner.tap("📥 Импорт")
    assert (await owner.tap("🤖 С ИИ")).startswith("🤖 Вставьте текстом")
    card = await owner.say(text)
    llm = long_world.llm
    assert isinstance(llm, FakeLlm) and len(llm.requests) == 3
    assert card.startswith("Понял так:\nПривычки: 120\nСтраница 1 из 12")
    await owner.tap("✅ Выполнить всё")
    assert len(await long_world.service("habits").entries_between(actor, date(2026, 10, 1), TODAY)) == 120


async def test_s151_import_weight_over_existing_day(world: World, owner: Persona) -> None:
    """S-151. Импорт веса за день, где взвешивание уже было, заменяет его; «↩️ Отменить всё» возвращает прежний вес."""
    actor = await _actor(world)
    profiles = world.service("users.profiles")
    await profiles.weigh_on(actor, YESTERDAY, Decimal("76"))
    await _start_import(owner)
    await owner.say(json.dumps([{"type": "weight.record", "day": "2026-11-02", "kg": 75.5}]))
    await owner.tap("✅ Выполнить всё")
    assert (await profiles.weights_between(actor, YESTERDAY, YESTERDAY)) == {YESTERDAY: Decimal("75.5")}
    await owner.tap("↩️ Отменить всё")
    assert (await profiles.weights_between(actor, YESTERDAY, YESTERDAY)) == {YESTERDAY: Decimal("76")}


async def test_s152_import_too_long_text_and_undo_nothing(world: World, owner: Persona) -> None:
    """S-152. Текст готовых действий больше 200 КБ (такой придёт только файлом) — «разбейте на части»; отмена
    взвешивания, которого уже нет, ничего не ломает."""
    actor = await _actor(world)
    with pytest.raises(AppError) as err:
        await world.service("ai_commands").import_actions(actor, "[" + " " * 200_001 + "]")
    assert "разбейте на части" in err.value.user_text()
    await world.service("users.profiles").unweigh_on(actor, date(2026, 10, 1), None)
    assert await world.service("users.profiles").weights_between(actor, date(2026, 10, 1), date(2026, 10, 1)) == {}
