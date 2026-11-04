"""Поведенческие сценарии: меню, ввод, отмена и сброс, дни (части 2 и 4)."""

from datetime import UTC, datetime

from tests.conftest import OTHER_ID
from tests.scenarios.conftest import finish_guest_onboarding, invite_guest
from tests.scenarios.harness import Persona, World

STALE = "Это меню устарело. Вот главное меню 👇"
FOREIGN = "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"


async def test_s13_walks_through_menu(world: World, owner: Persona) -> None:
    """S-13. Человек нажимает все кнопки меню подряд: разделы, которых ещё нет, отвечают «скоро» с номером части;
    непонятный текст и стикер — подсказка с меню."""
    for label, part in (("🏋️ Тренировка", 8), ("✅ Привычки", 7), ("📊 Итоги", 10)):
        assert await owner.tap(label) == f"{label} — скоро: раздел появится в части {part} плана."
    await owner.tap("☰ Ещё")
    assert all(owner.sees(b) for b in ("📅 Другой день", "✍️ Текстом", "🛌 Выходной", "⚙️ Настройки", "🛠 Админ"))
    await owner.tap("✍️ Текстом")
    assert owner.session.answers()[-1].text == "✍️ Текстом — скоро: раздел появится в части 9 плана."
    assert await owner.say("как дела?") == "Не понял. Выберите раздел в меню 👇"
    assert await owner.sticker() == "Не понял. Выберите раздел в меню 👇"


async def test_s14_left_for_coffee(world: World, owner: Persona) -> None:
    """S-14. Начал ввод, ушёл на 20 минут, вернулся и нажал кнопку старого вопроса: «Это меню устарело»,
    бот за это время ничего не присылал, число теперь не ждётся."""
    await owner.say("/check")
    await owner.say("178")
    sent = len(owner.texts())
    await world.wait(minutes=20)
    assert len(owner.texts()) == sent
    assert await owner.tap("✕ Отмена") == STALE
    assert await owner.say("5:45") == "Не понял. Выберите раздел в меню 👇"


async def test_s15_short_pause_keeps_input(world: World, owner: Persona) -> None:
    """S-15. Пауза 10 минут, затем бот перезапустился, ещё 3 минуты — ввод продолжается с того же шага."""
    await owner.say("/check")
    await world.wait(minutes=10)
    assert (await owner.say("178")).startswith("2/3.")
    await world.restart()
    await world.wait(minutes=3)
    assert (await owner.say("5.45")).startswith("3/3.")


async def test_s16_double_tap(world: World, owner: Persona) -> None:
    """S-16. Двойное нажатие «✅ Готово» (Telegram доставил нажатие дважды): одно «Готово», второе — «устарело»."""
    await owner.say("/check")
    await owner.say("178")
    await owner.say("5:45")
    await owner.say("вчера")
    await owner.tap_twice("✅ Готово")
    assert owner.replies() == ["Готово. Это была проверка — ничего не записано.", STALE]


async def test_s17_cancel_three_ways(world: World, owner: Persona) -> None:
    """S-17. Отмена кнопкой, словом и командой; повторная отмена — «Отменять нечего»."""
    await owner.say("/check")
    assert await owner.tap("✕ Отмена") == "Отменено, ничего не записано."
    for word in ("Отмена", "/cancel"):
        await owner.say("/check")
        assert await owner.say(word) == "Отменено, ничего не записано."
    assert await owner.say("/cancel") == "Отменять нечего. Вот главное меню 👇"


async def test_s18_forwarded_button(world: World, owner: Persona) -> None:
    """S-18. Гость нажимает кнопку с данными владельца (подмена) — отказ, ввод владельца не тронут."""
    guest = await invite_guest(world, owner, OTHER_ID, "Аня")
    await finish_guest_onboarding(guest)
    await owner.say("/check")
    owners_cancel = owner.find_button("✕ Отмена")
    await guest.press_data(owners_cancel)
    assert guest.last() == FOREIGN
    assert (await owner.say("178")).startswith("2/3.")


async def test_s19_forgot_yesterday(world: World, owner: Persona) -> None:
    """S-19. Вечером вспомнил про вчера: «Другой день» → «Вчера» → «Выходной» за вчера → «Вернуться к сегодня»."""
    world.set_time(datetime(2026, 10, 25, 18, 0, tzinfo=UTC))
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    assert (await owner.tap("Вчера (24.10)")).startswith("Записываю за 24.10.")
    assert owner.keyboard()[0] == ["📅 24.10 ✕ Вернуться к сегодня"]
    await owner.tap("☰ Ещё")
    assert (await owner.tap("🛌 Выходной")).startswith("🛌 24.10 — выходной")
    assert await owner.tap("📅 24.10 ✕ Вернуться к сегодня") == "Вернулись к сегодняшнему дню (25.10)."
    assert not owner.sees("📅 24.10 ✕ Вернуться к сегодня")


async def test_s20_other_day_forgotten(world: World, owner: Persona) -> None:
    """S-20. Включил «Другой день» и забыл: через 15 минут режим выключен молча; старая кнопка «Вернуться» —
    «Вы и так в сегодняшнем дне», клавиатура обычная."""
    await owner.tap("☰ Ещё")
    await owner.tap("📅 Другой день")
    await owner.tap("Позавчера (01.11)")
    sent = len(owner.texts())
    await world.wait(minutes=16)
    assert len(owner.texts()) == sent
    assert await owner.tap("📅 01.11 ✕ Вернуться к сегодня") == "Вы и так в сегодняшнем дне."
    assert owner.keyboard()[0] == ["🍽 Еда", "🤸 Зарядка"]


async def test_s21_night_owl(world: World, owner: Persona) -> None:
    """S-21. Сова отмечает выходной в 00:20 — он попадает во вчерашний день; в 04:05 — уже в новый."""
    world.set_time(datetime(2026, 10, 24, 21, 20, tzinfo=UTC))  # 25.10 00:20 по Москве
    await owner.tap("☰ Ещё")
    assert (await owner.tap("🛌 Выходной")).startswith("🛌 24.10")
    world.set_time(datetime(2026, 10, 25, 1, 5, tzinfo=UTC))  # 04:05
    await owner.tap("☰ Ещё")
    assert (await owner.tap("🛌 Выходной")).startswith("🛌 25.10")
