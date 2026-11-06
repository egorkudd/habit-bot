"""Поведенческие сценарии: «📊 Итоги» — картинка дня по выбранной привычке и обзор-светофор (раздел 3.8, часть 10).

Модель подключена (FakeLlm), но при построении статистики к ней не уходит ни одного запроса."""

import io
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest
from PIL import Image

from habit_bot.modules.food.domain.nutrition import Nutrients
from habit_bot.modules.food.domain.other_line import OtherLine
from habit_bot.modules.stats.domain.periods import Kind
from habit_bot.modules.stats.telegram import handlers as stats_ui
from habit_bot.modules.workouts.domain.training import Kind as WorkoutKind
from habit_bot.modules.workouts.domain.training import SetValue
from habit_bot.platform.stats.domain.traffic import Color
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.fakes import FakeLlm
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
OCT22 = date(2026, 10, 22)
# Еда 22.10 из критериев приёмки: 2 947 ккал / Б 189 / Ж 112 / У 289, расход 760 ₽, 3 блюда без цены.
MEALS_22 = [
    ("Коктейль", (322, 26, 9, 39), 140), ("Творог ужин", (421, "52.4", "15.6", "17.8"), 250),
    ("Куриное бедро", (500, 46, 34, 0), 370), ("Плов", (600, 20, 20, 80), None),
    ("Паста", (700, 30, 20, 100), None), ("Каша", ("404.24", "14.6", "13.4", "52.2"), None),
]


@pytest.fixture
async def stats_world(settings: Any, fake_session: Any, clock: Any, geocoder: Any,
                      monkeypatch: Any) -> AsyncIterator[World]:
    monkeypatch.setattr(stats_ui, "TEXT_BUTTON", True)  # кнопка «📝 Текстом» спрятана с 1.0.2, вид работает
    clock.current = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)  # регистрация до примера 22.10
    w = await World(settings, fake_session, clock, geocoder, llm=FakeLlm()).start()
    yield w
    await w.stop()


@pytest.fixture
async def me(stats_world: World) -> Persona:
    user = stats_world.person(ADMIN_ID, "Егор")
    await pass_onboarding(user)
    return user


async def actor_of(world: World) -> Any:
    return await world.service("users.sign_in").execute(ADMIN_ID, "")


async def eat_22(world: World) -> None:
    actor = await actor_of(world)
    for name, values, price in MEALS_22:
        await world.service("food").log_other(actor, OtherLine(name, Nutrients.of(*values),
                                                               Decimal(price) if price else None), day=OCT22)


def png_size(data: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(data)).size


def has_color(data: bytes, rgb: tuple[int, int, int]) -> bool:
    image = Image.open(io.BytesIO(data)).convert("RGB")
    return any(c == rgb for _, c in image.getcolors(maxcolors=1 << 20) or [])


async def test_s104_food_day_picture_and_text(stats_world: World, me: Persona) -> None:
    """S-104. Раздел 9: «Итоги» → «Еда» — картинка с 4 полосами и таблицей блюд; за 22.10 калории и белки —
    выполнено (чёрные), жиры 112 / 80 (140%) и углеводы 289 / 360 (80%) — частично (серые); расход 760 ₽, 3 блюда
    без цены; «Текстом» — та же таблица моноширинным блоком; ни одного запроса к ИИ."""
    await eat_22(stats_world)
    stats_world.set_time(datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
    assert await me.tap("📊 Итоги") == "📊 Еда · 22.10 (чт)"
    assert me.labels()[:2] == ["▸ 🍽 Еда", "🤸 Зарядка"]  # без точки «есть записи»
    assert "◀ 21.10" in me.labels() and "23.10 ▶" not in me.labels()  # будущее не листается
    picture = me.session.photos(ADMIN_ID)[-1]
    assert png_size(picture)[0] == 760
    assert has_color(picture, (33, 37, 41)) and has_color(picture, (160, 166, 173))  # выполнено и частично
    data = await stats_world.service("stats").day(await actor_of(stats_world), "food", OCT22)
    assert [(b.label, b.color) for b in data.bars] == [
        ("Ккал", Color.DONE), ("Белки", Color.DONE), ("Жиры", Color.PARTIAL), ("Углев", Color.PARTIAL)]
    text = await me.tap("📝 Текстом")
    assert text.startswith("<pre>Еда · 22.10 (чт)\nКкал   ████████████ 105%  2 947 / 2 800  ●\n")
    assert "Жиры   ████████████ 140%  112 / 80  ◐" in text
    assert "Углев  █████████▌░░  80%  289 / 360  ◐" in text
    assert "Расход: 760 ₽ · 3 блюда без цены" in text
    assert "Коктейль         322    26     9    39" in text
    assert stats_world.llm.requests == []


async def test_s105_choice_remembered_and_days_flipped(stats_world: World, me: Persona) -> None:
    """S-105. Бот запоминает последнюю выбранную привычку — и после перезапуска; «◀ / ▶» листают дни в том же
    сообщении; день без записей — «Записей нет»."""
    await me.tap("📊 Итоги")
    first = me.find_button_at("◀ 14.10")[1]
    assert await me.tap("🤸 Зарядка") == "📊 Зарядка · 15.10 (чт)"
    assert await me.tap("◀ 14.10") == "📊 Зарядка · 14.10 (ср)"
    assert me.find_button_at("15.10 ▶")[1] == first  # то же сообщение, картинка заменена
    assert "Записей нет" in await me.tap("📝 Текстом")
    await stats_world.restart()
    assert await me.tap("📊 Итоги") == "📊 Зарядка · 15.10 (чт)"
    assert "▸ 🤸 Зарядка" in me.labels()


async def test_s106_every_section_has_its_picture(stats_world: World, me: Persona) -> None:
    """S-106. Раздел 3.8.1: зарядка — «упражнение × зарядка» с ▲▼ к прошлому дню; тренировка — подходы, тоннаж,
    рекорд 🏆 и сравнение с прошлой; бег — темп, скорость, сравнение; своя привычка — факт / цель, отметки, серия."""
    actor = await actor_of(stats_world)
    warmup = stats_world.service("warmup")
    await warmup.use_default_set(actor)
    templates = {t.short: t.public_id for t in await warmup.templates(actor)}
    await warmup.record(actor, {templates["Отжимания"]: 50, templates["Планка"]: 345}, day=date(2026, 10, 14))
    await warmup.record(actor, {templates["Отжимания"]: 55, templates["Планка"]: 360}, day=date(2026, 10, 15))
    await warmup.record(actor, {templates["Отжимания"]: 60, templates["Планка"]: 360}, day=date(2026, 10, 15))
    workouts = stats_world.service("workouts")
    squat = next(e for e in await workouts.exercises(actor, await workouts.filters(actor, WorkoutKind.GYM))
                 if e.name == "Присед со штангой")
    await workouts.log_sets(actor, date(2026, 10, 13), [(squat.public_id, [SetValue(reps=8, weight=Decimal(105))] * 4)])
    await workouts.log_sets(actor, date(2026, 10, 15), [(squat.public_id, [SetValue(reps=8, weight=Decimal(110))] * 4)])
    runs = stats_world.service("runs")
    await runs.record(actor, distance_km=Decimal("5"), seconds=28 * 60, day=date(2026, 10, 13))
    await runs.record(actor, distance_km=Decimal("5.2"), seconds=28 * 60 + 40, day=date(2026, 10, 15))
    habits = stats_world.service("habits")
    eyes = await habits.from_template(actor, "eyes")
    await habits.mark(actor, eyes.public_id, day=date(2026, 10, 15))
    stats_world.clock.advance(hours=3)
    await habits.mark(actor, eyes.public_id, day=date(2026, 10, 15))

    await me.tap("📊 Итоги")  # первая привычка с записями — зарядка
    text = await me.tap("📝 Текстом")
    assert "Отжимания     55    60      ▲ +10" in text and "Планка      6:00  6:00    ▲ +0:15" in text
    assert "Зарядок" in text and "2 / 2  ●" in text
    text = await me.tap("🏋️ Тренировка")  # в текстовом виде разделы сразу показывают текст
    assert "Присед со штангой  110 кг 4×8  3 520 кг" in text
    assert "🏆 Рекорд: Присед со штангой 110 кг (было 105 кг)" in text and "▲ +160 кг к прошлой (13.10)" in text
    text = await me.tap("🏃 Бег")
    assert "5,2 км     28:40  5:31  10,88 км/ч" in text and "▲ на 0:05 быстрее прошлого" in text
    assert "🏆 Самая длинная дистанция: 5,2 км" in text
    text = await me.tap("👁 Глаза")
    assert "Глаза" in text and "2 / 3  ◐" in text and "Отметки: 12:00 +1 · 15:00 +1" in text
    assert stats_world.llm.requests == []


async def test_s107_week_traffic_light_with_day_off(stats_world: World, me: Persona) -> None:
    """S-107. Раздел 9: «Неделя» присылает одну картинку-светофор по всем целям; клетки «Выходного» серые;
    справа — % зелёных и серия; «◀» — прошлая неделя, будущие дни пустые; «Текстом» — значки по дням."""
    await eat_22(stats_world)
    actor = await actor_of(stats_world)
    stats_world.set_time(datetime(2026, 10, 24, 12, 0, tzinfo=UTC))
    await stats_world.service("days").toggle_day_off(actor, date(2026, 10, 24))
    food = stats_world.service("food")
    await food.log_other(actor, OtherLine("Ужин", Nutrients.of(2700, 150, 85, 350), None), day=date(2026, 10, 21))
    await food.log_other(actor, OtherLine("Ужин", Nutrients.of(2000, 100, 60, 250), None), day=date(2026, 10, 24))
    stats_world.set_time(datetime(2026, 10, 23, 12, 0, tzinfo=UTC))
    await me.tap("📊 Итоги")
    assert await me.tap("Неделя") == "📊 Неделя · 19.10–25.10"
    assert me.labels() == ["◀", "▸ Неделя", "Месяц", "3 месяца", "📝 Текстом", "📊 День"]  # ▶ — в будущее нет
    overview = await stats_world.service("stats").overview(actor, Kind.WEEK)
    kcal = next(r for r in overview.rows if r.label == "Калории")
    assert kcal.cells == (Color.NONE, Color.NONE, Color.DONE, Color.DONE, Color.NONE, Color.FUTURE, Color.FUTURE)
    assert (kcal.green, kcal.streak) == (50, 2)  # сегодня (23.10) ещё не закончилось — серию не обрывает
    text = await me.tap("📝 Текстом")
    assert "Калории  ○○●●○    50% · серия 2" in text and "в выходной" in text
    assert (await me.tap("◀")).startswith("<pre>Неделя · 12.10–18.10\n")  # текстовый вид сохраняется
    assert "▶" in me.labels()
    assert await me.tap("🖼 Картинкой") == "📊 Неделя · 12.10–18.10"
    stats_world.set_time(datetime(2026, 10, 26, 12, 0, tzinfo=UTC))
    after = await stats_world.service("stats").overview(actor, Kind.WEEK, -1)
    assert next(r for r in after.rows if r.label == "Калории").cells[5] is Color.OFF  # 24.10 — выходной «в»
    assert stats_world.llm.requests == []


async def test_s108_month_quarter_and_rules(stats_world: World, me: Persona) -> None:
    """S-108. «Месяц» и «3 месяца» — одна картинка, клетки помельче, подписи вмещаются; в тексте за 3 месяца —
    только % и серия; привычки, зарядка, тренировки и вес — по правилам раздела 4.10."""
    actor = await actor_of(stats_world)
    stats_world.set_time(datetime(2026, 10, 21, 12, 0, tzinfo=UTC))
    habits = stats_world.service("habits")
    eyes = await habits.from_template(actor, "eyes")
    for day, times in ((15, 3), (16, 1), (17, 0)):
        for _ in range(times):
            await habits.mark(actor, eyes.public_id, day=date(2026, 10, day))
    warmup = stats_world.service("warmup")
    await warmup.use_default_set(actor)
    plank = next(t.public_id for t in await warmup.templates(actor) if t.short == "Планка")
    await warmup.record(actor, {plank: 345}, day=date(2026, 10, 15))
    profiles = stats_world.service("users.profiles")
    stats_world.set_time(datetime(2026, 10, 13, 9, 0, tzinfo=UTC))
    await profiles.update_profile(actor, weight_kg=Decimal("74.5"))
    stats_world.set_time(datetime(2026, 10, 20, 9, 0, tzinfo=UTC))
    await profiles.update_profile(actor, weight_kg=Decimal("75.5"))  # набор массы — вес растёт
    await stats_world.service("workouts").log_sets(actor, date(2026, 10, 14), [])
    stats_world.set_time(datetime(2026, 10, 21, 12, 0, tzinfo=UTC))
    await me.tap("📊 Итоги")
    assert await me.tap("Месяц") == "📊 Месяц · октябрь 2026"
    assert png_size(me.session.photos(ADMIN_ID)[-1])[0] < 1300
    assert await me.tap("3 месяца") == "📊 3 месяца · август–октябрь 2026"
    text = await me.tap("📝 Текстом")
    assert "👁 Глаза" in text and "% · серия" in text and "●" not in text.split("\n", 2)[1]
    month = await stats_world.service("stats").overview(actor, Kind.MONTH)
    rows = {r.label: r.cells for r in month.rows}
    # до анкеты — бледная; 3/3 — чёрная, 1/3 — серая, 0/3 — белая
    assert rows["👁 Глаза"][13:17] == (Color.SKIP, Color.DONE, Color.PARTIAL, Color.NONE)
    assert rows["Зарядка"][14] is Color.PARTIAL and rows["Зарядка"][15] is Color.NONE  # 1 из 2, ни одной
    assert rows["Вес"][19] is Color.DONE and rows["Вес"][12] is Color.NONE  # неделя 19.10 тяжелее прошлой
    assert rows["Тренировки"][13] is Color.PARTIAL  # 14.10: тренировка, а за неделю 1 из 3
    assert rows["Тренировки"][14] is Color.NONE and rows["Тренировки"][20] is Color.NONE  # без тренировки — белые
    assert stats_world.llm.requests == []


async def test_s109_foreign_and_old_buttons(stats_world: World, me: Persona) -> None:
    """S-109. Изоляция: гость не может нажать кнопки «Итогов» владельца; кнопка удалённой привычки — «Записей
    нет» не ломает экран: показывается выбор заново."""
    actor = await actor_of(stats_world)
    eyes = await stats_world.service("habits").from_template(actor, "eyes")
    await me.tap("📊 Итоги")
    week = me.find_button("Неделя")
    habit_button = me.find_button("👁 Глаза")
    guest = await invite_guest(stats_world, me, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await guest.press_data(week)
    assert guest.last() == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    await stats_world.service("habits").delete(actor, eyes.public_id)
    await me.press_data(habit_button)
    assert me.last() == "📊 Еда · 15.10 (чт)"
    await guest.tap("📊 Итоги")
    assert guest.last() == "📊 Еда · 15.10 (чт)" and "👁 Глаза" not in guest.labels()


async def test_s124_pressing_open_section_again(stats_world: World, me: Persona) -> None:
    """S-124. «📊 Итоги» → «🤸 Зарядка», затем снова «▸ 🤸 Зарядка» (или «Неделя» дважды): картинка та же — Telegram
    отвечает «message is not modified», бот молчит, без ⚠️ E-xxxx и оповещения администратору."""
    await me.tap("📊 Итоги")
    sent = len(me.texts())
    assert await me.tap("🤸 Зарядка") == "📊 Зарядка · 15.10 (чт)"
    assert await me.tap("▸ 🤸 Зарядка") == "📊 Зарядка · 15.10 (чт)"
    await me.tap("Неделя")
    await me.tap("▸ Неделя")
    assert len(me.texts()) == sent
    assert await me.tap("📊 День") == "📊 Зарядка · 15.10 (чт)"


async def test_s126_text_view_replaces_the_same_message(stats_world: World, me: Persona) -> None:
    """S-126. «📝 Текстом» — отдельной строкой, не между стрелками; меняет текущее сообщение, а не присылает новое:
    в чате остаётся одно сообщение «Итогов»; «◀ / ▶», разделы и периоды в текстовом виде меняют текст на месте;
    «🖼 Картинкой» возвращает картинку."""
    await eat_22(stats_world)
    stats_world.set_time(datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
    await me.tap("📊 Итоги")
    labels = me.labels()
    assert labels[-5:] == ["◀ 21.10", "Неделя", "Месяц", "3 месяца", "📝 Текстом"]
    before = [t for t in me.on_screen() if "Еда · " in t]
    assert len(before) == 1
    text = await me.tap("📝 Текстом")
    assert text.startswith("<pre>Еда · 22.10 (чт)\nКкал ")
    assert me.labels()[-1] == "🖼 Картинкой"
    assert len([t for t in me.on_screen() if "Еда · " in t]) == 1  # картинка заменена текстом, не добавлен второй
    message_id = me.find_button_at("◀ 21.10")[1]
    assert (await me.tap("◀ 21.10")).startswith("<pre>Еда · 21.10 (ср)")
    assert me.find_button_at("22.10 ▶")[1] == message_id  # тот же текст поменялся на месте
    assert (await me.tap("Неделя")).startswith("<pre>Неделя · 19.10–25.10")
    assert me.find_button_at("📊 День")[1] == message_id
    assert await me.tap("🖼 Картинкой") == "📊 Неделя · 19.10–25.10"
    assert len([t for t in me.on_screen() if "Неделя" in t or "Еда · " in t]) == 1
    assert stats_world.llm.requests == []


async def test_s127_workout_visible_in_unfinished_week(stats_world: World, me: Persona) -> None:
    """S-127. Анкета на этой неделе, тренировка и бег сегодня: в «Неделе» и «Месяце» строка «Тренировки» видна —
    день тренировки серый, пока цель недели (3) не выполнена; после 3-й тренировки за неделю — чёрный;
    дни без тренировки белые; через неделю итог недели остаётся на днях тренировок."""
    from habit_bot.modules.workouts.domain.training import Kind as WorkoutKind
    from habit_bot.modules.workouts.domain.training import SetValue

    actor = await actor_of(stats_world)
    workouts = stats_world.service("workouts")
    squat = next(e for e in await workouts.exercises(actor, await workouts.filters(actor, WorkoutKind.GYM))
                 if e.name == "Присед со штангой")
    stats_world.set_time(datetime(2026, 10, 16, 9, 0, tzinfo=UTC))  # пт; неделя 12–18.10 идёт
    await workouts.log_sets(actor, date(2026, 10, 16), [(squat.public_id, [SetValue(reps=8, weight=Decimal(100))])])
    stats = stats_world.service("stats")
    week = {r.label: r for r in (await stats.overview(actor, Kind.WEEK)).rows}
    assert week["Тренировки"].cells == (Color.SKIP, Color.SKIP, Color.SKIP, Color.NONE, Color.PARTIAL, Color.FUTURE,
                                        Color.FUTURE)
    month = {r.label: r for r in (await stats.overview(actor, Kind.MONTH)).rows}
    assert month["Тренировки"].cells[15] is Color.PARTIAL
    await me.tap("📊 Итоги")
    await me.tap("Неделя")
    assert "Тренировки  ···○◐  " in await me.tap("📝 Текстом")
    await stats_world.service("runs").record(actor, distance_km=Decimal(5), seconds=1700, day=date(2026, 10, 15))
    await workouts.log_sets(actor, date(2026, 10, 16), [(squat.public_id, [SetValue(reps=8, weight=Decimal(100))])])
    row = {r.label: r for r in (await stats.overview(actor, Kind.WEEK)).rows}["Тренировки"]
    assert row.cells[3:5] == (Color.DONE, Color.DONE) and (row.green, row.streak) == (100, 1)
    stats_world.set_time(datetime(2026, 10, 26, 9, 0, tzinfo=UTC))
    row = {r.label: r for r in (await stats.overview(actor, Kind.WEEK, -2)).rows}["Тренировки"]  # 12–18.10
    assert row.cells == (Color.SKIP, Color.SKIP, Color.SKIP, Color.DONE, Color.DONE, Color.NONE, Color.NONE)


async def test_s128_day_off_and_today_progress(stats_world: World, me: Persona) -> None:
    """S-128. Выходной виден: в обзоре — клетка «в» во всех строках, на картинке дня — «· выходной» в заголовке.
    Прогресс сегодняшнего дня виден в «Неделе» и «Месяце»: часть цели — серая клетка, сегодняшний столбец в рамке;
    пока день не закончился, он не обрывает серию. На кнопках разделов нет точки."""
    actor = await actor_of(stats_world)
    eyes = await stats_world.service("habits").from_template(actor, "eyes")
    stats_world.set_time(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))  # ср
    await stats_world.service("days").toggle_day_off(actor, date(2026, 10, 20))
    for day, times in ((date(2026, 10, 19), 3), (date(2026, 10, 21), 1)):
        for _ in range(times):
            await stats_world.service("habits").mark(actor, eyes.public_id, day=day)
    stats = stats_world.service("stats")
    for kind in (Kind.WEEK, Kind.MONTH):
        data = await stats.overview(actor, kind)
        assert data.today == date(2026, 10, 21)
        row = next(r for r in data.rows if r.label == "👁 Глаза")
        i = data.days.index(date(2026, 10, 19))
        assert row.cells[i:i + 3] == (Color.DONE, Color.OFF, Color.PARTIAL)  # 3/3, выходной, сегодня 1/3
        assert row.streak == 1  # сегодня ещё идёт — серия с понедельника не оборвалась
    await me.tap("📊 Итоги")
    assert not any("•" in label for label in me.labels())
    await me.tap("Неделя")
    assert "👁 Глаза  ●в◐      100% · серия 1" in await me.tap("📝 Текстом")
    await me.tap("📊 День")
    assert "· 20.10 (вт) · выходной\n" in await me.tap("◀ 20.10")


async def test_s129_schedule_and_day_off_in_workouts(stats_world: World, me: Persona) -> None:
    """S-129. Привычка по расписанию «пн, ср»: во вторник клетка бледная (не по плану), а не белая; в строке
    «Тренировки» выходной без тренировки — «в», а не белая клетка."""
    actor = await actor_of(stats_world)
    eyes = await stats_world.service("habits").from_template(actor, "eyes")
    await stats_world.service("habits").update(actor, eyes.public_id, weekdays=[0, 2])
    workouts = stats_world.service("workouts")
    squat = next(e for e in await workouts.exercises(actor, await workouts.filters(actor, WorkoutKind.GYM))
                 if e.name == "Присед со штангой")
    stats_world.set_time(datetime(2026, 10, 21, 9, 0, tzinfo=UTC))  # ср
    await stats_world.service("days").toggle_day_off(actor, date(2026, 10, 20))
    await workouts.log_sets(actor, date(2026, 10, 19), [(squat.public_id, [SetValue(reps=8, weight=Decimal(100))])])
    await stats_world.service("habits").mark(actor, eyes.public_id, day=date(2026, 10, 19))
    rows = {r.label: r for r in (await stats_world.service("stats").overview(actor, Kind.WEEK)).rows}
    assert rows["Тренировки"].cells[:3] == (Color.PARTIAL, Color.OFF, Color.NONE)
    stats_world.set_time(datetime(2026, 10, 23, 9, 0, tzinfo=UTC))  # пт; вт выходной снят
    await stats_world.service("days").toggle_day_off(actor, date(2026, 10, 20))
    rows = {r.label: r for r in (await stats_world.service("stats").overview(actor, Kind.WEEK)).rows}
    assert rows["👁 Глаза"].cells[1] is Color.SKIP and rows["👁 Глаза"].cells[3] is Color.SKIP


async def test_s133_text_button_hidden(stats_world: World, me: Persona, monkeypatch: Any) -> None:
    """S-133. Правки 1.0.2: кнопки «📝 Текстом» нет ни у картинки дня, ни у обзора; старая кнопка «Текстом» ещё
    работает и предлагает «🖼 Картинкой», после чего кнопки снова нет."""
    monkeypatch.setattr(stats_ui, "TEXT_BUTTON", False)
    await eat_22(stats_world)
    stats_world.set_time(datetime(2026, 10, 22, 20, 0, tzinfo=UTC))
    await me.tap("📊 Итоги")
    assert "📝 Текстом" not in me.labels() and me.labels()[-1] == "3 месяца"
    await me.tap("Неделя")
    assert me.labels()[-1] == "📊 День" and "📝 Текстом" not in me.labels()
    actor = await actor_of(stats_world)
    old = stats_ui.StCb(o=actor.user_id, t=0, a="per", v="w0", m="t").pack()
    await me.press_data(old, message_id=me.message_id_of(me._mine()[-1]) or 500)
    assert "🖼 Картинкой" in me.labels()
    await me.tap("🖼 Картинкой")
    assert "📝 Текстом" not in me.labels()
