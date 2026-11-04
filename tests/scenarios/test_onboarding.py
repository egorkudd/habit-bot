"""Поведенческие сценарии: анкета (раздел 3.0) — человек ошибается, отвлекается, возвращается."""

from sqlalchemy import select

from habit_bot.modules.users.models import Goal, Profile
from tests.conftest import ADMIN_ID, OTHER_ID
from tests.scenarios.conftest import invite_guest, pass_onboarding
from tests.scenarios.harness import Persona, World

REMIND = "Анкету нельзя отменить, но можно прерваться — продолжим с того же шага. Ответьте на вопрос 👇"


async def test_s07_owner_first_run(world: World) -> None:
    """S-07. Владелец впервые пишет боту: анкета целиком → норма 2800/160/80/360 → меню → /start — приветствие."""
    owner = world.person(ADMIN_ID, "Егор")
    await pass_onboarding(owner)
    assert owner.last() == "Хорошо. Главное меню внизу 👇"
    assert owner.keyboard()[0] == ["🍽 Еда", "🤸 Зарядка"]
    assert (await owner.say("/start")).startswith("Привет, администратор")
    async with world.app.ctx.uow() as uow:
        goal = (await uow.session.execute(select(Goal))).scalar_one()
    assert (goal.kcal, goal.protein, goal.fat, goal.carbs) == (2800, 160, 80, 360)


async def test_s08_typos_and_back(world: World) -> None:
    """S-08. Человек ошибается: буквы вместо роста, «1780», будущая дата рождения — подсказки, шаг не теряется;
    «← Назад» исправляет прошлый ответ."""
    user = world.person(ADMIN_ID, "Егор")
    await user.say("/start")
    await user.tap("Егор")
    await user.tap("Мужской")
    assert await user.say("15 марта") == "Дату пишите как 20.10 или 20.10.2026"
    assert (await user.say("15.03.2030")).startswith("Нельзя записать на 15.03 — это будущее.")
    await user.say("15.03.2003")
    assert await user.say("сто восемьдесят") == "Не понял число „сто восемьдесят“. Напишите, например, 4,5 или 4.5"
    assert await user.say("1780") == "Рост — от 120 до 230 см. Вы ввели 1780 — может, лишняя цифра?"
    assert (await user.say("178")).startswith("Шаг 5/12. Текущий вес")
    assert (await user.tap("← Назад")).startswith("Шаг 4/12. Рост")
    assert (await user.say("180")).startswith("Шаг 5/12.")
    assert (await user.say("77,5")).startswith("Шаг 6/12.")


async def test_s09_tries_to_escape(world: World) -> None:
    """S-09. Посреди анкеты человек жмёт «отмена», /cancel, пишет «🍽 Еда», шлёт стикер — анкета напоминает вопрос,
    ничего не сбрасывается."""
    user = world.person(ADMIN_ID, "Егор")
    await user.say("/start")
    await user.tap("Егор")
    for action in ("отмена", "/cancel", "🍽 Еда"):
        await user.say(action)
        assert user.replies() == [REMIND, "Шаг 2/12. Пол:"]
    await user.sticker()
    assert user.replies() == [REMIND, "Шаг 2/12. Пол:"]


async def test_s10_old_buttons_in_onboarding(world: World) -> None:
    """S-10. Человек листает вверх и жмёт кнопку прошлого шага — бот повторяет текущий вопрос."""
    user = world.person(ADMIN_ID, "Егор")
    await user.say("/start")
    await user.tap("Егор")
    await user.tap("Мужской")
    await user.press(user.first_name)  # кнопка имени с первого шага
    assert user.last().startswith("Шаг 3/12. Дата рождения")


async def test_s11_comes_back_next_day_after_restart(world: World) -> None:
    """S-11. Бросил анкету на 6-м шаге, бот перезапускался, вернулся через сутки — продолжает с того же шага."""
    user = world.person(ADMIN_ID, "Егор")
    await user.say("/start")
    await user.tap("Егор")
    await user.tap("Мужской")
    await user.say("15.03.2003")
    await user.say("178")
    await user.say("75")
    await world.restart()
    await world.wait(days=1)
    await user.say("/start")
    assert user.replies() == ["Продолжим анкету с того же места.", user.last()]
    assert user.last().startswith("Шаг 6/12. Уровень активности")


async def test_s12_two_people_at_once(world: World, owner: Persona) -> None:
    """S-12. Два человека проходят анкету одновременно, ответы чередуются — данные не смешиваются."""
    anya = await invite_guest(world, owner, OTHER_ID, "Аня")
    await owner.tap("☰ Ещё")
    await owner.tap("🛠 Админ")
    await owner.tap("🎟 Приглашения")
    await owner.tap("➕ Новое приглашение")
    await owner.tap("1")
    code = (await owner.tap("7 дней")).split("?start=")[1].split()[0]
    olya = world.person(333333333, "Оля")
    await olya.say(f"/start {code}")
    steps = [("tap", "self"), ("tap", "Женский"), ("say", "10.01.1996"), ("say", "165"), ("say", "60"),
             ("tap", "Средняя"), ("tap", "Поддержание"), ("tap", "Пропустить"), ("tap", "Новичок"),
             ("tap", "Заполнить позже")]
    olya_steps = [("tap", "self"), ("tap", "Женский"), ("say", "01.01.2000"), ("say", "170"), ("say", "55"),
                  ("tap", "Лёгкая"), ("tap", "Набор массы"), ("tap", "Пропустить"), ("tap", "Средний"),
                  ("tap", "Заполнить позже")]
    for (a_kind, a_value), (o_kind, o_value) in zip(steps, olya_steps, strict=True):
        for person, kind, value in ((anya, a_kind, a_value), (olya, o_kind, o_value)):
            value = person.first_name if value == "self" else value
            await (person.tap(value) if kind == "tap" else person.say(value))
    async with world.app.ctx.uow() as uow:
        profiles = {p.height_cm: p for p in (await uow.session.execute(select(Profile))).scalars().all()}
    assert profiles[165].weight_kg == 60 and profiles[165].goal_mode == "maintain"
    assert profiles[170].weight_kg == 55 and profiles[170].goal_mode == "gain"
