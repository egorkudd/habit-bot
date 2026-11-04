"""Часть 3, раздел 3.0 и критерии раздела 9 «Регистрация и профиль», «Изоляция», «Город»: анкета, приглашения,
профиль с пересчётом, цели, удаление аккаунта."""

from datetime import date
from typing import Any

from sqlalchemy import select

from habit_bot.app import build_app
from habit_bot.kernel.identity import Identity, User, UserStatus
from habit_bot.modules.users.models import BodyWeight, Goal, Invite, Profile
from habit_bot.modules.users.telegram.fields import UCb
from tests.conftest import ADMIN_ID, OTHER_ID, register_active
from tests.fakes import TgChat

THIRD_ID = 333333333


async def _rows(app: Any, model: Any) -> list[Any]:
    async with app.ctx.uow() as uow:
        return list((await uow.session.execute(select(model))).scalars().all())


async def _owner_until_kbju(chat: TgChat) -> None:
    await chat.say("/start")
    await chat.press("Егор")
    await chat.press("Мужской")
    await chat.say("15.03.2003")
    await chat.say("178")
    await chat.say("75")
    await chat.press("Лёгкая")
    await chat.press("Набор массы")
    await chat.press("Пропустить")
    await chat.press("Средний")


async def test_owner_onboarding(app: Any, fake_session: Any) -> None:
    """Раздел 9: владелец /start без ссылки → анкета → 2800 / 160 / 80 / 360 и роль «Администратор»."""
    chat = TgChat(app, fake_session, ADMIN_ID)
    await _owner_until_kbju(chat)
    assert chat.texts()[-1] == "Шаг 10/12. Город — для погоды по утрам:"
    assert chat.labels() == ["Москва", "Санкт-Петербург", "Череповец", "Другой", "Пропустить", "← Назад",
                             "Заполнить позже"]
    question = await chat.press("Москва")
    assert question == "Шаг 11/12. Ваша норма в день:\n2 800 ккал · Б 160 · Ж 80 · У 360"
    assert (await chat.press("✅ Принять")).startswith("Шаг 12/12. Стартовый набор")
    await chat.press("☐ Базовые продукты")
    await chat.press("☑ Базовые продукты")
    await chat.press("☐ Примеры привычек")
    await chat.press("Готово")
    texts = chat.texts()
    assert texts[-2] == "Готово, Егор! Норма с сегодняшнего дня:\n2 800 ккал · Б 160 · Ж 80 · У 360"
    assert texts[-1].startswith("Можно сразу внести")

    (profile,) = await _rows(app, Profile)
    assert (profile.city_name, profile.timezone, profile.starter_kit) == ("Москва", "Europe/Moscow", ["habits"])
    (goal,) = await _rows(app, Goal)
    assert (goal.kcal, goal.protein, goal.fat, goal.carbs, goal.source) == (2800, 160, 80, 360, "calc")
    (weight,) = await _rows(app, BodyWeight)
    assert weight.weight_kg == 75
    (user,) = await _rows(app, User)
    assert user.status is UserStatus.ACTIVE and user.name == "Егор"

    await chat.press("Позже")
    assert chat.texts()[-1] == "Хорошо. Главное меню внизу 👇"
    assert (await chat.say("/start")).startswith("Привет, администратор")


async def test_onboarding_errors_back_and_resume(settings: Any, fake_session: Any, clock: Any, geocoder: Any) -> None:
    """Ошибка ввода не сбрасывает шаг; «← Назад» возвращает; прерванная анкета продолжается после перезапуска."""
    first = build_app(settings, telegram_session=fake_session, clock=clock, geocoder=geocoder)
    await first.startup()
    chat = TgChat(first, fake_session, ADMIN_ID)
    await chat.say("/start")
    assert await chat.say("   ") == "Имя — от 1 до 32 символов. Сейчас 0"
    await chat.say("Егор")
    await chat.press("Мужской")
    assert await chat.say("15.03.2027") == "Нельзя записать на 15.03 — это будущее. Сегодня 03.11"
    assert await chat.say("1780") == "Дату пишите как 20.10 или 20.10.2026"
    await chat.say("15.03.2003")
    assert await chat.say("1780") == "Рост — от 120 до 230 см. Вы ввели 1780 — может, лишняя цифра?"
    assert (await chat.press("← Назад")).startswith("Шаг 3/12. Дата рождения")
    assert (await chat.say("отмена")).startswith("Шаг 3/12.")
    await first.close()

    clock.advance(days=1)  # анкета не сбрасывается по бездействию
    second = build_app(settings, telegram_session=fake_session, clock=clock, geocoder=geocoder)
    await second.startup()
    try:
        chat = TgChat(second, fake_session, ADMIN_ID)
        await chat.say("/start")
        assert chat.texts()[-2:] == ["Продолжим анкету с того же места.",
                                     "Шаг 3/12. Дата рождения — ДД.ММ.ГГГГ, например 15.03.2003."]
        await chat.say("15.03.2003")
        await chat.say("178")
        await chat.say("75")
        await chat.press("Лёгкая")
        await chat.press("Набор массы")
        assert await chat.say("70") == "Целевой вес при наборе — от 75,5 до 250 кг. Вы ввели 70"
        await chat.say("80")
        await chat.press("Средний")
        await chat.press("Заполнить позже")
        assert chat.texts()[-2].startswith("Готово, Егор!")
        (profile,) = await _rows(second, Profile)
        assert profile.city_name is None and profile.target_weight == 80 and profile.starter_kit == []
    finally:
        await second.close()


async def test_old_step_button_and_manual_kbju(app: Any, fake_session: Any) -> None:
    """Кнопка прошлого шага повторяет текущий вопрос; КБЖУ вручную с предупреждением о расхождении."""
    chat = TgChat(app, fake_session, ADMIN_ID)
    await _owner_until_kbju(chat)
    old = chat.find_button("Мужской")
    await chat.press_data(old)
    assert chat.texts()[-1].startswith("Шаг 10/12.")
    await chat.press("Другой")
    assert await chat.say("Масква") == "Не нашёл город „Масква“. Может, Москва? Или напишите иначе"
    assert (await chat.press("Москва")).startswith("Шаг 11/12.")
    await chat.press("✏️ Изменить вручную")
    assert await chat.say("2800 160 80") == (
        "Напишите 4 числа через пробел: ккал, белки, жиры, углеводы. Пример: 2800 160 80 360")
    await chat.say("2000 160 80 360")
    assert "⚠️ По Б·4 + Ж·9 + У·4 выходит 2 800 ккал" in chat.texts()[-2]
    await chat.press("Готово")
    (goal,) = await _rows(app, Goal)
    assert (goal.kcal, goal.source) == (2000, "manual")


async def test_city_choices_in_onboarding(app: Any, fake_session: Any) -> None:
    """Раздел 9: «Кировск» — выбор с регионами; сервис не отвечает — снова кнопки городов."""
    chat = TgChat(app, fake_session, ADMIN_ID)
    await _owner_until_kbju(chat)
    await chat.press("Другой")
    assert await chat.say("сломано") == "Шаг 10/12. Город — для погоды по утрам:"
    assert chat.texts()[-2].startswith("Поиск городов сейчас не отвечает.")
    await chat.press("Другой")
    assert await chat.say("Кировск") == "Шаг 10/12. Нашлось несколько — выберите:"
    assert chat.labels()[:3] == ["Кировск, Ленинградская обл.", "Кировск, Могилевская обл.", "Кировск, Мурманская обл."]
    await chat.press("Кировск, Ленинградская обл.")
    await chat.press("✅ Принять")
    await chat.press("Готово")
    (profile,) = await _rows(app, Profile)
    assert (profile.city_name, profile.city_region, profile.city_lat) == ("Кировск", "Ленинградская обл.", 59.8756)


async def test_invites_flow(app: Any, fake_session: Any, clock: Any) -> None:
    """Раздел 9: приглашение на 1 человека; повторно, отозванный и истёкший код не работают."""
    admin = await register_active(app)
    invites = app.ctx.services["users.invites"]
    once = await invites.create(admin, max_uses=1, days=7)
    guest = TgChat(app, fake_session, OTHER_ID, "Аня")
    assert (await guest.say(f"/start {once.code}")).startswith("Шаг 1/12. Как к вам обращаться?")
    third = TgChat(app, fake_session, THIRD_ID, "Оля")
    assert await third.say(f"/start {once.code}") == (
        "Эта ссылка больше не действует (все места уже заняты). Попросите новую у того, кто её прислал")
    revoked = await invites.create(admin, max_uses=3, days=0)
    assert await invites.revoke(admin, revoked.public_id) is True
    assert await invites.revoke(admin, revoked.public_id) is False
    assert "(отозвана)" in await third.say(f"/start {revoked.code}")
    short = await invites.create(admin, max_uses=3, days=1)
    clock.advance(days=2)
    assert "(истекла 04.11)" in await third.say(f"/start {short.code}")
    assert await third.say("/start неизвестный") == (
        "Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз")
    (_, guest_user) = await _rows(app, User)
    assert guest_user.invite_id is not None and guest_user.role.value == "user"


async def test_admin_invites_ui(app: Any, fake_session: Any) -> None:
    """«Админ» → «Приглашения»: создать на 5 человек на 7 дней, увидеть в списке, отозвать."""
    await register_active(app)
    chat = TgChat(app, fake_session, ADMIN_ID)
    await chat.say("☰ Ещё")
    await chat.press("🛠 Админ")
    assert await chat.press("🎟 Приглашения") == "🎟 Приглашения\nДействующих приглашений нет."
    await chat.press("➕ Новое приглашение")
    await chat.press("5")
    text = await chat.press("7 дней")
    assert "Приглашение готово (на 5 человек, до 10.11)" in text
    assert "https://t.me/habit_test_bot?start=" in text
    assert "1. на 5 человек · использовано 0/5 · до 10.11" in text
    assert await chat.press("✕ Отозвать 1") == "🎟 Приглашения\nДействующих приглашений нет."
    (invite,) = await _rows(app, Invite)
    assert invite.revoked_at is not None


async def test_guest_cannot_manage_invites(app: Any, fake_session: Any) -> None:
    """Подменённая кнопка администратора от обычного пользователя — отказ, приглашение не создано."""
    admin = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(admin, max_uses=2, days=1)
    guest = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    chat = TgChat(app, fake_session, OTHER_ID, "Аня")
    await chat.say("☰ Ещё")
    assert "🛠 Админ" not in chat.labels()
    await chat.press_data(UCb(o=guest.user_id, t=0, a="inv_days", v="5_7").pack())
    assert chat.texts()[-1] == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert len(await _rows(app, Invite)) == 1


async def test_weight_change_offers_recalc(app: Any, fake_session: Any) -> None:
    """Раздел 3.0: изменение веса предлагает пересчёт; новая цель — с сегодня; вес пишется в историю."""
    await register_active(app)
    chat = TgChat(app, fake_session, ADMIN_ID)
    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    assert (await chat.press("👤 Профиль")).startswith("👤 Профиль\nИмя: Егор")
    await chat.press("Вес")
    text = await chat.say("80")
    assert text.startswith("Сохранено ✅\nНовые КБЖУ: 2 900 ккал · Б 170 · Ж 85 · У 365")
    assert "\nСейчас: 2 800 ккал · Б 160 · Ж 80 · У 360" in text
    text = await chat.press("🔄 Пересчитать")
    assert text.startswith("Новая цель с 03.11: 2 900 ккал")
    goals = await _rows(app, Goal)
    assert len(goals) == 2
    (weight,) = await _rows(app, BodyWeight)
    assert weight.weight_kg == 80

    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    await chat.press("👤 Профиль")
    await chat.press("Рост")
    await chat.say("190")
    assert (await chat.press("Оставить как есть")).startswith("КБЖУ оставлены как есть.")
    assert len(await _rows(app, Goal)) == 2


async def test_profile_fields_without_recalc(app: Any, fake_session: Any) -> None:
    """Имя, опыт и город меняются сразу; одинаковые КБЖУ не предлагают пересчёт."""
    await register_active(app)
    chat = TgChat(app, fake_session, ADMIN_ID)
    profiles = app.ctx.services["users.profiles"]

    async def open_field(label: str) -> None:
        await chat.say("☰ Ещё")
        await chat.press("⚙️ Настройки")
        await chat.press("👤 Профиль")
        await chat.press(label)

    await open_field("Имя")
    assert "Имя: Егорий" in await chat.say("Егорий")
    await open_field("Опыт")
    assert "Опыт тренировок: Продвинутый" in await chat.press("Продвинутый")
    await open_field("Город")
    await chat.press("Другой")
    assert "Город: Ростов-на-Дону, Ростовская обл." in await chat.say("Ростов-на-Дону")
    await open_field("Город")
    await chat.press("Другой")
    await chat.say("Масква")
    assert "Город: Москва" in await chat.press("Москва")
    await open_field("Город")
    assert "Город: не указан" in await chat.press("Убрать город")
    await open_field("Город")
    await chat.press("Другой")
    assert (await chat.say("сломано")).startswith("Город — для погоды")
    await chat.press("✕ Отмена")
    await open_field("Пол")
    assert (await chat.press("Мужской")).startswith("Сохранено ✅ КБЖУ не изменились.")
    await open_field("Активность")
    assert (await chat.press("Лёгкая")).startswith("Сохранено ✅ КБЖУ не изменились.")
    await open_field("Цель")
    assert "Новые КБЖУ" in await chat.press("Поддержание")
    await chat.press("Оставить как есть")
    await open_field("Дата рождения")
    assert "Новые КБЖУ" in await chat.say("15.03.1993")
    await chat.press("Оставить как есть")
    await open_field("Целевой вес")
    assert "Целевой вес: 76 кг" in await chat.say("76")
    await open_field("Пол")
    assert await chat.say("мужской") == "Выберите вариант кнопкой выше 👆"
    view = await profiles.profile(await app.ctx.services["users.sign_in"].execute(ADMIN_ID, ""))
    assert view.name == "Егорий" and view.city is None and view.birth_date == date(1993, 3, 15)


async def test_goals_screen(app: Any, fake_session: Any, clock: Any) -> None:
    """Цели КБЖУ: история; ручной ввод; цель на дату — по действовавшей, до первой — первая."""
    actor = await register_active(app)
    chat = TgChat(app, fake_session, ADMIN_ID)
    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    text = await chat.press("🎯 Цели КБЖУ")
    assert text == "🎯 Цели КБЖУ (новые сверху):\n• сегодня: 2 800 ккал · Б 160 · Ж 80 · У 360 (расчёт)"
    clock.advance(days=1)
    await chat.press("✏️ Ввести вручную")
    text = await chat.say("2410 140 70 305")
    assert text.startswith("Новая цель с 04.11: 2 410 ккал · Б 140 · Ж 70 · У 305")
    assert "• с 03.11: 2 800 ккал" in text
    await chat.press("🔄 Пересчитать по профилю")
    profiles = app.ctx.services["users.profiles"]
    assert (await profiles.goal_on(actor, date(2026, 11, 3))).kcal == 2800
    assert (await profiles.goal_on(actor, date(2026, 1, 1))).kcal == 2800
    assert len(await profiles.goals(actor)) == 3


async def test_delete_account(app: Any, fake_session: Any) -> None:
    """Раздел 9: удаление стирает все данные и Identity; последний администратор удалиться не может."""
    admin = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(admin, max_uses=1, days=1)
    guest = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня")
    profiles = app.ctx.services["users.profiles"]

    chat = TgChat(app, fake_session, ADMIN_ID)
    await chat.say("☰ Ещё")
    await chat.press("⚙️ Настройки")
    await chat.press("🗑 Удалить аккаунт")
    assert await chat.press("🗑 Да, удалить всё") == (
        "Вы единственный администратор — аккаунт удалить нельзя. "
        "Сначала добавьте ещё один Telegram-ID в секрет ADMIN_TG_IDS")

    other = TgChat(app, fake_session, OTHER_ID, "Аня")
    await other.say("/check")
    await other.say("☰ Ещё")
    await other.press("⚙️ Настройки")
    assert await other.press("🗑 Удалить аккаунт") == "Удалить аккаунт и все данные? Это нельзя отменить."
    assert await other.press("🗑 Да, удалить всё") == (
        "Аккаунт и все данные удалены. Чтобы начать заново, напишите /start.")
    assert await profiles.count_user_rows(guest.user_id) == 0
    identities = await _rows(app, Identity)
    assert [i.external_id for i in identities] == [str(ADMIN_ID)]
    deleted = next(u for u in await _rows(app, User) if u.id == guest.user_id)
    assert (deleted.status, deleted.name) == (UserStatus.DELETED, "")
    assert await profiles.count_user_rows(admin.user_id) > 0
    assert await other.say("привет") == "Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз"


async def test_isolation(app: Any, fake_session: Any) -> None:
    """Раздел 9 «Изоляция»: B не видит профиль и цели A; кнопка A, подменённая B, получает отказ."""
    admin = await register_active(app)
    invite = await app.ctx.services["users.invites"].create(admin, max_uses=1, days=1)
    guest = await register_active(app, OTHER_ID, invite_code=invite.code, name="Аня", sex="female",
                                  birth_date="1996-01-10", height_cm="165", weight_kg="60", activity="medium",
                                  mode="maintain")
    profiles = app.ctx.services["users.profiles"]
    a, b = await profiles.profile(admin), await profiles.profile(guest)
    assert (a.name, b.name) == ("Егор", "Аня")
    assert [g.kcal for g in await profiles.goals(guest)] == [2050]
    chat = TgChat(app, fake_session, OTHER_ID, "Аня")
    await chat.press_data(UCb(o=admin.user_id, t=0, a="settings", v="profile").pack())
    assert chat.texts()[-1] == "Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇"
    assert await profiles.profile(guest) == b
