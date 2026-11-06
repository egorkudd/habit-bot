"""Поведенческие сценарии: экспорт своих данных в CSV (раздел 3.12, часть 10)."""

import csv
import io
import zipfile
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from habit_bot.modules.food.domain.nutrition import Nutrients
from habit_bot.modules.food.domain.other_line import OtherLine
from habit_bot.modules.workouts.domain.training import Kind as WorkoutKind
from habit_bot.modules.workouts.domain.training import SetValue
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World
from tests.scenarios.test_stats import MEALS_22, OCT22

FILES = ["daily_summary.csv", "food.csv", "warmups.csv", "workouts.csv", "runs.csv", "habits.csv", "body_weight.csv",
         "goals.csv", "profile.csv", "README.csv"]


@pytest.fixture
async def export_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> AsyncIterator[World]:
    clock.current = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)
    w = await World(settings, fake_session, clock, geocoder).start()
    yield w
    await w.stop()


@pytest.fixture
async def me(export_world: World) -> Persona:
    user = export_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    actor = await export_world.service("users.sign_in").execute(ADMIN_ID, "")
    food = export_world.service("food")
    for name, values, price in MEALS_22:
        await food.log_other(actor, OtherLine(name, Nutrients.of(*values), Decimal(price) if price else None),
                             day=OCT22)
    workouts = export_world.service("workouts")
    squat = next(e for e in await workouts.exercises(actor, await workouts.filters(actor, WorkoutKind.GYM))
                 if e.name == "Присед со штангой")
    await workouts.log_sets(actor, OCT22, [(squat.public_id, [SetValue(reps=8, weight=Decimal(110))] * 4)])
    await export_world.service("runs").record(actor, distance_km=Decimal("5.2"), seconds=1720, day=OCT22)
    eyes = await export_world.service("habits").from_template(actor, "eyes")
    export_world.set_time(datetime(2026, 10, 22, 17, 30, tzinfo=UTC))
    await export_world.service("habits").mark(actor, eyes.public_id, day=OCT22)
    return user


def table(raw: bytes) -> list[dict[str, str]]:
    assert raw.startswith(b"\xef\xbb\xbf")  # BOM — Excel открывает без «кракозябр»
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))


async def open_export(user: Persona) -> str:
    await user.tap("☰ Ещё")
    await user.tap("⚙️ Настройки")
    return await user.tap("📦 Экспорт")


async def test_s110_month_as_files(export_world: World, me: Persona) -> None:
    """S-110. Раздел 9: экспорт за период — CSV из раздела 3.12 и README.csv; за 22.10 в daily_summary.csv
    kcal = 2947.24, kcal_goal = 2800, cost_rub = 760 с десятичной точкой; подход «4×8» — 4 строки в workouts.csv;
    имени и Telegram-ID нет ни в одном файле."""
    assert await open_export(me) == "📦 Экспорт своих данных в CSV — для таблиц и нейросетей. За какой период?"
    assert await me.tap("Месяц") == "📦 Экспорт за 23.09.2026–22.10.2026. Отметьте, что выгрузить:"
    assert me.labels()[:2] == ["✅ Итоги по дням", "✅ Еда"]
    result = await me.tap("📄 Файлами")
    assert result == "✅ Экспорт за 23.09.2026–22.10.2026: 10 файлов. Имени и Telegram-ID в файлах нет."
    files = dict(me.session.documents(ADMIN_ID))
    assert list(files) == FILES
    day = next(r for r in table(files["daily_summary.csv"]) if r["date"] == "2026-10-22")
    assert (day["kcal"], day["kcal_goal"], day["cost_rub"], day["kcal_left"]) == ("2947.24", "2800", "760", "-147.24")
    assert (day["day_status"], day["workouts"], day["run_km"], day["warmups_goal"]) == ("normal", "1", "5.2", "2")
    food = table(files["food.csv"])
    assert food[1] == {"date": "2026-10-22", "time": "12:00", "name": "Творог ужин", "quantity": "1",
                       "unit": "portion", "kcal": "421", "protein": "52.4", "fat": "15.6", "carbs": "17.8",
                       "cost_rub": "250", "source": "other"}
    sets = table(files["workouts.csv"])
    assert [(s["exercise"], s["set_no"], s["weight_kg"], s["reps"]) for s in sets] == [
        ("Присед со штангой", str(n), "110", "8") for n in range(1, 5)]
    assert table(files["runs.csv"])[0]["pace_sec_per_km"] == "331"
    assert table(files["habits.csv"])[0]["habit"] == "Зарядка для глаз"
    assert table(files["goals.csv"])[0]["kcal"] == "2800"
    assert table(files["profile.csv"])[0]["city"] == "Москва"
    readme = table(files["README.csv"])
    assert {r["file"] for r in readme} == set(FILES[:-1])
    assert any(r["column"] == "kcal_left" and r["unit"] == "ккал" for r in readme)
    for name, raw in files.items():
        text = raw.decode("utf-8-sig")
        assert "Егор" not in text and str(ADMIN_ID) not in text, name


async def test_s111_checkboxes_and_archive(export_world: World, me: Persona) -> None:
    """S-111. Галочки снимаются и ставятся в том же сообщении; без галочек — подсказка; «🗜 Одним архивом» —
    ZIP с теми же файлами; после выгрузки старые кнопки устарели."""
    await open_export(me)
    await me.tap("Неделя")
    for title in ("Итоги по дням", "Зарядка", "Тренировки", "Бег", "Привычки", "Вес тела", "Цели КБЖУ", "Профиль"):
        await me.tap(f"✅ {title}")
    assert me.labels()[:2] == ["▫️ Итоги по дням", "✅ Еда"]
    await me.tap("✅ Еда")
    await me.tap("📄 Файлами")
    assert me.session.answers()[-1].text == "Отметьте хотя бы одну таблицу"
    await me.tap("▫️ Еда")
    await me.tap("▫️ Бег")
    zip_button = me.find_button("🗜 Одним архивом")
    assert (await me.tap("🗜 Одним архивом")).startswith("✅ Экспорт за 16.10.2026–22.10.2026: архив ZIP.")
    name, data = me.session.documents(ADMIN_ID)[-1]
    assert name == "habit-bot-export.zip"
    with zipfile.ZipFile(io.BytesIO(data)) as zipped:
        assert zipped.namelist() == ["food.csv", "runs.csv", "README.csv"]
        assert len(table(zipped.read("food.csv"))) == 6
    sent = len(me.session.documents(ADMIN_ID))
    await me.press_data(zip_button)
    assert len(me.session.documents(ADMIN_ID)) == sent + 1  # кнопка без состояния: повторная выгрузка безопасна


async def test_s112_custom_dates_with_mistakes(export_world: World, me: Persona) -> None:
    """S-112. «📅 Выбрать даты»: одна дата — подсказка, будущая — ошибка, ввод не сбрасывается; даты в обратном
    порядке понимаются; «Всё время»; «✕ Отмена» — ничего не выгружено."""
    await open_export(me)
    assert await me.tap("📅 Выбрать даты") == "📅 Напишите две даты через тире: 01.10–22.10"
    assert await me.say("вчера") == "Напишите две даты через тире: 01.10–22.10 или 01.10.2026–22.10.2026"
    assert await me.say("01.10–25.10") == "Нельзя записать на 25.10 — это будущее. Сегодня 22.10"
    assert await me.say("с 22.10 по 20.10") == "📦 Экспорт за 20.10.2026–22.10.2026. Отметьте, что выгрузить:"
    await me.tap("📄 Файлами")
    rows = table(dict(me.session.documents(ADMIN_ID))["daily_summary.csv"])
    assert [r["date"] for r in rows] == ["2026-10-22"]
    await open_export(me)
    assert await me.tap("Всё время") == "📦 Экспорт за всё время. Отметьте, что выгрузить:"
    assert await me.tap("✕ Отмена") == "Отменено, ничего не выгружено."


async def test_s113_isolation_and_delete_account_offer(export_world: World, me: Persona) -> None:
    """S-113. Раздел 9: экспорт содержит только свои данные; гость не может нажать кнопку экспорта владельца;
    «Удалить аккаунт» предлагает сначала скачать экспорт."""
    guest = await invite_guest(export_world, me, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await open_export(me)
    owner_month = me.find_button("Месяц")
    await guest.press_data(owner_month)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    await open_export(guest)
    await guest.tap("Всё время")
    await guest.tap("📄 Файлами")
    files = dict(me.session.documents(OTHER_ID))
    assert table(files["food.csv"]) == [] and table(files["workouts.csv"]) == []
    assert table(files["profile.csv"])[0]["sex"] == "female"
    assert all("Аня" not in raw.decode("utf-8-sig") for raw in files.values())
    await guest.tap("☰ Ещё")
    await guest.tap("⚙️ Настройки")
    assert await guest.tap("🗑 Удалить аккаунт") == "Удалить аккаунт и все данные? Это нельзя отменить."
    assert await guest.tap("📦 Сначала скачать экспорт") == (
        "📦 Экспорт своих данных в CSV — для таблиц и нейросетей. За какой период?")
