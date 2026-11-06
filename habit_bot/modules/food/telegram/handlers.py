"""«🍽 Еда» в Telegram (раздел 3.2): рецепты кнопками, вес и штуки, множитель, «Другое», записи дня, каталог,
свои рецепты и продукты. Логика — в ``Food``; здесь только кнопки и тексты."""

from __future__ import annotations

import html
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import dialog_token, start_dialog
from habit_bot.channels.telegram.dialogs.policy import LOST_DAY, OTHER_DAY
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb, move_button
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.days import quick_days
from habit_bot.kernel.domain.formatting import format_day, format_number
from habit_bot.kernel.domain.parsing import ensure_not_future, parse_date, parse_number
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.days.public import Days
from habit_bot.modules.food.domain.nutrition import QUICK_AMOUNTS, Nutrients, Unit, quantity_label
from habit_bot.modules.food.domain.other_line import parse_other_line, parse_values_line
from habit_bot.modules.food.usecases import PRODUCT, RECIPE, EntryView, Food, ItemView

KIND = "food"
FOOD_TITLE = "🍽 Еда за {day}. Нажмите блюдо — запишу 1 порцию."
EMPTY_LIST = "🍽 Еда за {day}. Своих рецептов и продуктов пока нет — добавьте из «📚 Каталог» или создайте в «⚙️ Мои»."
OTHER_PROMPT = ("Одной строкой: название, ккал, белки, жиры, углеводы, [цена]. "
                "Пример: Маффин 320 4,5 15 41 90")
VALUES_PROMPT = "Одной строкой: ккал, белки, жиры, углеводы на {unit}, [цена]. Пример: 322 26 9 39 140"
TODAY_NOTE = "Записываю за сегодня."
ITEMS_PER_SCREEN = 24
UNIT_NAMES = {Unit.PORTION: "порцию", Unit.GRAMS: "100 г", Unit.PIECE: "1 шт"}
UNIT_BUTTONS = {Unit.PORTION.value: "Порция", Unit.GRAMS.value: "На 100 г", Unit.PIECE.value: "За 1 шт"}
PORTION_AMOUNTS = (Decimal("0.5"), Decimal(1), Decimal("1.5"), Decimal(2))


class FCb(CallbackData, prefix="f"):
    o: int
    t: int
    a: str
    v: str | None = None


class EntryCb(CallbackData, prefix="fe"):
    """Кнопки под карточкой записи: действуют 24 часа (``m`` — минута создания)."""

    o: int
    t: int
    a: str
    i: str
    m: int


class FoodInput(StatesGroup):
    qty = State()
    other = State()
    edit_qty = State()
    move_day = State()
    recipe_name = State()
    new_name = State()
    new_unit = State()
    new_values = State()
    edit_values = State()
    edit_name = State()


DayCard = Callable[[Actor, date], Awaitable[str]]


def values_text(n: Nutrients, price: Decimal | None) -> str:
    f = format_number
    cost = f" · {f(price)} ₽" if price is not None else " · без цены"
    return f"{f(n.kcal)} ккал · Б {f(n.protein)} · Ж {f(n.fat)} · У {f(n.carbs)}{cost}"


def item_line(item: ItemView) -> str:
    unit = {Unit.GRAMS: "100 г", Unit.PIECE: "1 шт"}.get(item.unit, item.portion_label or "порция")
    return f"{item.name} — на {unit}: {values_text(item.nutrients, item.price)}"


def entry_line(entry: EntryView) -> str:
    return (f"{entry.name} — {quantity_label(entry.unit, entry.quantity, entry.portion_label)}: "
            f"{values_text(entry.nutrients, entry.price)}")


def build_food_router(
    food: Food, days: Days, screens: Screens, day_card: Callable[[], DayCard | None],
) -> tuple[Router, Router]:
    """Два роутера: «🍽 Еда» с клавиатуры (подключается первым — работает и посреди чужого ввода) и остальное."""
    router = Router(name="food")
    nav = Router(name="food.nav")

    def fbtn(actor: Actor, token: int, text: str, action: str, value: str | None = None) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=FCb(o=actor.user_id, t=token, a=action, v=value).pack())

    def ebtn(actor: Actor, text: str, action: str, entry_id: str) -> InlineKeyboardButton:
        data = EntryCb(o=actor.user_id, t=0, a=action, i=entry_id, m=minute()).pack()
        return InlineKeyboardButton(text=text, callback_data=data)

    def cancel(actor: Actor, token: int) -> InlineKeyboardButton:
        return InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())

    def minute() -> int:
        return int(days.now().timestamp() // 60)

    def rows_of(buttons: list[InlineKeyboardButton], per_row: int = 2) -> list[list[InlineKeyboardButton]]:
        return fit_rows(buttons, per_row)  # длинное название рецепта — одно в ряду, чтобы не обрезалось

    def message_id(query: CallbackQuery) -> int | None:
        return query.message.message_id if query.message is not None else None

    async def card(actor: Actor, day: date) -> str:
        render = day_card()
        return await render(actor, day) if render else ""

    async def send_card(bot: Bot, chat_id: int, actor: Actor, text: str, day: date,
                        markup: InlineKeyboardMarkup | None = None) -> None:
        body = f"{html.escape(text)}\n{await card(actor, day)}"
        await bot.send_message(chat_id, body, parse_mode="HTML", reply_markup=markup)

    async def show_entry(bot: Bot, chat_id: int, actor: Actor, entry: EntryView, *, other: bool = False,
                         prefix: str = "") -> None:
        """Карточка новой записи — итог ввода: «×0,5», «×2», «Отменить», «📅 На вчера» (по 2 в ряд);
        у «Другого» — «Сохранить как рецепт». Промежуточные сообщения ввода удаляются."""
        rows = fit_rows([ebtn(actor, "×0,5", "x05", entry.public_id), ebtn(actor, "×2", "x2", entry.public_id),
                         ebtn(actor, "Отменить", "undo", entry.public_id),
                         move_button(actor.user_id, KIND, entry.public_id, minute())])
        lost = await screens.dialogs.get(actor.user_id, LOST_DAY)
        if lost is not None and lost.state == "on" and lost.other_day and lost.other_day != entry.day \
                and await screens.dialogs.day(actor.user_id, OTHER_DAY) is None:
            # Раздел 3: «Другой день» сбросился — запись не должна незаметно попасть не в тот день.
            await screens.dialogs.set_state(actor.user_id, LOST_DAY, "shown", days.now())
            prefix = f"{TODAY_NOTE}\n{prefix}"
            rows.append([ebtn(actor, f"📅 Нет, за {format_day(lost.other_day)}", "lost", entry.public_id)])
        if other:
            rows.append([ebtn(actor, "💾 Сохранить как рецепт", "save", entry.public_id)])
        trail.result()
        await send_card(bot, chat_id, actor, f"{prefix}🍽 {entry_line(entry)}", entry.day,
                        inline(rows))

    # --- экран «Еда» ---
    async def food_screen(bot: Bot, chat_id: int, actor: Actor, day: date) -> None:
        await food.apply_starter_kit(actor)
        items = await food.items(actor)
        buttons = [fbtn(actor, 0, i.name, "log", i.public_id) for i in items[:ITEMS_PER_SCREEN]]
        rows = rows_of(buttons)
        rows.append([fbtn(actor, 0, "✍️ Другое", "other"), fbtn(actor, 0, "📋 Записи дня", "entries")])
        rows.append([fbtn(actor, 0, "📚 Каталог", "cat"), fbtn(actor, 0, "⚙️ Мои", "my")])
        title = (FOOD_TITLE if items else EMPTY_LIST).format(day=format_day(day))
        await bot.send_message(chat_id, title, reply_markup=inline(rows))

    def is_food_label(text: str | None) -> bool:
        entry = screens.menu.get("food")
        return entry is not None and text is not None and text.strip() == entry.label

    @nav.message(F.text.func(is_food_label))
    async def open_food(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await state.clear()  # переход в раздел закрывает незаконченный ввод
        await food_screen(bot, message.chat.id, actor, record_day)

    @nav.callback_query(MenuCb.filter(F.k == KIND))
    async def open_food_from_more(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext,
                                  record_day: date) -> None:
        """«🍽 Еда» убрана с главного экрана — открывается из «✅ Привычки» (MenuCb с тем же ключом)."""
        await screens.close_buttons(query)
        await state.clear()
        await food_screen(bot, query.from_user.id, actor, record_day)

    # --- запись из своего списка ---
    @router.callback_query(FCb.filter(F.a == "log"))
    async def log(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor, state: FSMContext,
                  record_day: date, request_id: str | None) -> None:
        item = await food.item(actor, callback_data.v or "")
        if item is None or not item.active:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await query.answer()
        if item.unit is Unit.PORTION:
            entry = await food.log_item(actor, item.public_id, quantity=Decimal(1), day=record_day,
                                        request_id=request_id)
            await show_entry(bot, query.from_user.id, actor, entry)
            return
        token = await start_dialog(state, FoodInput.qty, record_day)
        await state.update_data(item=item.public_id)
        unit = "г" if item.unit is Unit.GRAMS else "шт"
        amounts = [fbtn(actor, token, f"{a} {unit}", "q", str(a)) for a in QUICK_AMOUNTS[item.unit]]
        question = f"{item.name}: сколько? Кнопкой или числом ({'граммы' if unit == 'г' else 'штуки'})."
        await bot.send_message(query.from_user.id, question,
                               reply_markup=inline([amounts, [cancel(actor, token)]]))

    async def log_amount(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, record_day: date,
                         amount: Decimal, request_id: str | None) -> None:
        item_id = (await state.get_data()).get("item", "")
        entry = await food.log_item(actor, item_id, quantity=amount, day=record_day, request_id=request_id)
        await state.clear()
        await show_entry(bot, chat_id, actor, entry)

    @router.callback_query(StateFilter(FoodInput.qty), FCb.filter(F.a == "q"))
    async def amount_button(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor, state: FSMContext,
                            record_day: date, request_id: str | None) -> None:
        await screens.close_buttons(query)
        await log_amount(bot, query.from_user.id, actor, state, record_day, Decimal(callback_data.v or "0"),
                         request_id)

    @router.message(StateFilter(FoodInput.qty), F.text)
    async def amount_text(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                          request_id: str | None) -> None:
        await log_amount(bot, message.chat.id, actor, state, record_day, parse_number(message.text or ""),
                         request_id)

    # --- «Другое» ---
    @router.callback_query(FCb.filter(F.a == "other"))
    async def other(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, record_day: date) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, FoodInput.other, record_day)
        await bot.send_message(query.from_user.id, OTHER_PROMPT,
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.message(StateFilter(FoodInput.other), F.text)
    async def other_line(message: Message, bot: Bot, actor: Actor, state: FSMContext, record_day: date,
                         request_id: str | None) -> None:
        line = parse_other_line(message.text or "")  # ошибка — подсказка, ввод остаётся
        entry = await food.log_other(actor, line, day=record_day, request_id=request_id)
        await state.clear()
        await show_entry(bot, message.chat.id, actor, entry, other=True)

    # --- кнопки под карточкой записи ---
    @router.callback_query(EntryCb.filter())
    async def entry_action(query: CallbackQuery, callback_data: EntryCb, bot: Bot, actor: Actor,
                           state: FSMContext, today: date) -> None:
        if minute() - callback_data.m > 24 * 60:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        entry_id, action, chat_id = callback_data.i, callback_data.a, query.from_user.id
        current = await food.entry(actor, entry_id)
        if current is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        if action in {"x05", "x2"}:
            await screens.close_buttons(query)
            trail.discard(message_id(query))  # старая карточка с прежним количеством больше не нужна
            updated = await food.multiply(actor, entry_id, Decimal("0.5") if action == "x05" else Decimal(2))
            await show_entry(bot, chat_id, actor, updated)
        elif action in {"undo", "del"}:
            await screens.close_buttons(query)
            await food.delete_entry(actor, entry_id)
            if action == "undo":
                trail.discard(message_id(query))
            trail.result()
            await send_card(bot, chat_id, actor, f"Запись «{current.name}» удалена.", current.day)
        elif action == "lost":
            lost_day = await screens.dialogs.day(actor.user_id, LOST_DAY)
            if lost_day is None:
                await screens.refuse_button(bot, query, actor, "UI-STALE")
                return
            await screens.close_buttons(query, toast=f"Перенесено на {format_day(lost_day)}")
            await screens.dialogs.clear(actor.user_id, LOST_DAY)
            await days.move(actor, KIND, entry_id, lost_day)
            trail.discard(message_id(query))
            trail.result()
            await send_card(bot, chat_id, actor, f"«{current.name}» — за {format_day(lost_day)}.", lost_day)
        elif action == "save":
            await save_recipe(query, bot, actor, state, entry_id)
        elif action == "saveup":
            await screens.close_buttons(query)
            recipe = await food.save_other_as_recipe(actor, entry_id, overwrite=True)
            trail.result()
            await bot.send_message(chat_id, f"Рецепт «{recipe.name}» обновлён: {values_text(recipe.nutrients,
                                                                                        recipe.price)}")
        elif action == "savenm":
            await screens.close_buttons(query)
            token = await start_dialog(state, FoodInput.recipe_name)
            await state.update_data(entry=entry_id)
            await bot.send_message(chat_id, "Как назвать рецепт?",
                                   reply_markup=inline([[cancel(actor, token)]]))
        elif action == "open":
            await screens.close_buttons(query)
            rows = [[ebtn(actor, "✏️ Изменить количество", "qty", entry_id)],
                    [ebtn(actor, "🗑 Удалить", "del", entry_id), ebtn(actor, "📅 Перенести на дату", "mvd", entry_id)]]
            await bot.send_message(chat_id, f"🍽 {entry_line(current)}",
                                   reply_markup=inline(rows))
        elif action == "qty":
            await screens.close_buttons(query)
            token = await start_dialog(state, FoodInput.edit_qty)
            await state.update_data(entry=entry_id)
            if current.unit is Unit.PORTION:
                amounts = [fbtn(actor, token, f"×{format_number(a)}", "eq", str(a)) for a in PORTION_AMOUNTS]
            else:
                unit = "г" if current.unit is Unit.GRAMS else "шт"
                amounts = [fbtn(actor, token, f"{a} {unit}", "eq", str(a)) for a in QUICK_AMOUNTS[current.unit]]
            await bot.send_message(chat_id, f"{current.name}: новое количество?",
                                   reply_markup=inline([amounts, [cancel(actor, token)]]))
        else:  # mvd — перенести на дату
            await screens.close_buttons(query)
            token = await start_dialog(state, FoodInput.move_day)
            await state.update_data(entry=entry_id)
            buttons = [fbtn(actor, token, label, "mvto", d.isoformat()) for label, d in quick_days(today, 4)
                       if d != current.day]
            await bot.send_message(chat_id, "На какой день перенести? Кнопкой или датой: 20.10.",
                                   reply_markup=inline([*rows_of(buttons),
                                                                                      [cancel(actor, token)]]))

    async def save_recipe(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext, entry_id: str) -> None:
        await screens.close_buttons(query)
        try:
            recipe = await food.save_other_as_recipe(actor, entry_id)
        except AppError as err:
            if err.code != "INPUT-DUPLICATE":
                raise
            rows = [[ebtn(actor, "Обновить", "saveup", entry_id),
                     ebtn(actor, "Сохранить под другим именем", "savenm", entry_id)]]
            await bot.send_message(query.from_user.id, err.user_text(),
                                   reply_markup=inline(rows))
            return
        trail.result()
        await bot.send_message(query.from_user.id, f"Рецепт «{recipe.name}» сохранён — он теперь в списке «🍽 Еда».")

    @router.message(StateFilter(FoodInput.recipe_name), F.text)
    async def recipe_name(message: Message, actor: Actor, state: FSMContext) -> None:
        entry_id = (await state.get_data()).get("entry", "")
        recipe = await food.save_other_as_recipe(actor, entry_id, name=" ".join((message.text or "").split()))
        await state.clear()
        trail.result()
        await message.answer(f"Рецепт «{recipe.name}» сохранён — он теперь в списке «🍽 Еда».")

    async def change_qty(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, amount: Decimal) -> None:
        entry_id = (await state.get_data()).get("entry", "")
        updated = await food.set_quantity(actor, entry_id, amount)
        await state.clear()
        trail.result()
        await send_card(bot, chat_id, actor, f"Изменено: {entry_line(updated)}", updated.day)

    @router.callback_query(StateFilter(FoodInput.edit_qty), FCb.filter(F.a == "eq"))
    async def qty_button(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await change_qty(bot, query.from_user.id, actor, state, Decimal(callback_data.v or "1"))

    @router.message(StateFilter(FoodInput.edit_qty), F.text)
    async def qty_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await change_qty(bot, message.chat.id, actor, state, parse_number(message.text or ""))

    async def move_to(bot: Bot, chat_id: int, actor: Actor, state: FSMContext, day: date, today: date) -> None:
        ensure_not_future(day, today)
        entry_id = (await state.get_data()).get("entry", "")
        result = await days.move(actor, KIND, entry_id, day)
        await state.clear()
        if result is None:
            await screens.home(bot, chat_id, actor, "Запись уже удалена.")
            return
        trail.result()
        for shown in (result.new_day, result.old_day):
            await send_card(bot, chat_id, actor, f"Итоги {format_day(shown)}:", shown)

    @router.callback_query(StateFilter(FoodInput.move_day), FCb.filter(F.a == "mvto"))
    async def move_button_pressed(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor,
                                  state: FSMContext, today: date) -> None:
        await screens.close_buttons(query)
        await move_to(bot, query.from_user.id, actor, state, date.fromisoformat(callback_data.v or ""), today)

    @router.message(StateFilter(FoodInput.move_day), F.text)
    async def move_text(message: Message, bot: Bot, actor: Actor, state: FSMContext, today: date) -> None:
        await move_to(bot, message.chat.id, actor, state, parse_date(message.text or "", today), today)

    # --- записи дня ---
    @router.callback_query(FCb.filter(F.a == "entries"))
    async def entries(query: CallbackQuery, bot: Bot, actor: Actor, record_day: date) -> None:
        await screens.close_buttons(query)
        found = await food.entries(actor, record_day)
        if not found:
            await send_card(bot, query.from_user.id, actor, f"Записей еды за {format_day(record_day)} нет.",
                            record_day)
            return
        buttons = [ebtn(actor, f"{e.name} · {format_number(e.nutrients.kcal)} ккал", "open", e.public_id)
                   for e in found]
        await send_card(bot, query.from_user.id, actor, f"📋 Записи еды за {format_day(record_day)} — выберите:",
                        record_day, inline(rows_of(buttons, 1)))

    # --- каталог ---
    @router.callback_query(FCb.filter(F.a == "cat"))
    async def catalog(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        buttons = [fbtn(actor, 0, i.name, "ci", i.public_id) for i in await food.catalog()]
        await bot.send_message(query.from_user.id, "📚 Каталог — нажмите продукт:",
                               reply_markup=inline(rows_of(buttons)))

    @router.callback_query(FCb.filter(F.a == "ci"))
    async def catalog_item(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        item = next((i for i in await food.catalog() if i.public_id == callback_data.v), None)
        if item is None:
            return
        markup = inline([[fbtn(actor, 0, "➕ Добавить к себе", "cadd", item.public_id)]])
        await bot.send_message(query.from_user.id, item_line(item), reply_markup=markup)

    @router.callback_query(FCb.filter(F.a == "cadd"))
    async def catalog_add(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        item, added = await food.add_from_catalog(actor, callback_data.v or "")
        text = f"«{item.name}» добавлен в ваш список." if added else f"«{item.name}» уже в вашем списке."
        trail.result()
        markup = inline([[fbtn(actor, 0, "Записать сейчас", "log", item.public_id)]])
        await bot.send_message(query.from_user.id, text, reply_markup=markup)

    # --- свои рецепты и продукты ---
    async def my_items(bot: Bot, chat_id: int, actor: Actor) -> None:
        items = await food.items(actor, include_hidden=True)
        buttons = [fbtn(actor, 0, ("" if i.active else "🙈 ") + i.name, "it", i.public_id) for i in items]
        rows = [*rows_of(buttons), [fbtn(actor, 0, "➕ Новый рецепт или продукт", "new")]]
        await bot.send_message(chat_id, "⚙️ Мои рецепты и продукты:", reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows))

    @router.callback_query(FCb.filter(F.a == "my"))
    @router.callback_query(MenuCb.filter(F.k == "food_items"))
    async def my(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await my_items(bot, query.from_user.id, actor)

    @router.callback_query(FCb.filter(F.a == "it"))
    async def my_item(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        item = await food.item(actor, callback_data.v or "")
        if item is None:
            return
        toggle = ("🙈 Скрыть", "ihide") if item.active else ("👁 Показать", "ishow")
        rows = [[fbtn(actor, 0, "✏️ КБЖУ и цена", "ied", item.public_id),
                 fbtn(actor, 0, "✏️ Название", "inm", item.public_id)],
                [fbtn(actor, 0, toggle[0], toggle[1], item.public_id)]]
        await bot.send_message(query.from_user.id, item_line(item), reply_markup=InlineKeyboardMarkup(
            inline_keyboard=rows))

    @router.callback_query(FCb.filter(F.a.in_({"ihide", "ishow"})))
    async def hide(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        item = await food.update_item(actor, callback_data.v or "", active=callback_data.a == "ishow")
        state_text = "показан в списке" if item.active else "скрыт — прошлые записи остались"
        trail.result()
        await bot.send_message(query.from_user.id, f"«{item.name}» {state_text}.")

    @router.callback_query(FCb.filter(F.a.in_({"ied", "inm"})))
    async def edit_item(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        item = await food.item(actor, callback_data.v or "")
        if item is None:
            return
        target = FoodInput.edit_values if callback_data.a == "ied" else FoodInput.edit_name
        token = await start_dialog(state, target)
        await state.update_data(item=item.public_id)
        prompt = VALUES_PROMPT.format(unit=UNIT_NAMES[item.unit]) if callback_data.a == "ied" else "Новое название?"
        await bot.send_message(query.from_user.id, prompt,
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.message(StateFilter(FoodInput.edit_values), F.text)
    async def edit_values(message: Message, actor: Actor, state: FSMContext) -> None:
        nutrients, price = parse_values_line(message.text or "")
        item = await food.update_item(actor, (await state.get_data()).get("item", ""), nutrients=nutrients,
                                      price=price)
        await state.clear()
        trail.result()
        await message.answer(f"Сохранено: {item_line(item)}\nПрошлые записи не изменились.")

    @router.message(StateFilter(FoodInput.edit_name), F.text)
    async def edit_name(message: Message, actor: Actor, state: FSMContext) -> None:
        item = await food.update_item(actor, (await state.get_data()).get("item", ""),
                                      name=" ".join((message.text or "").split())[:64])
        await state.clear()
        trail.result()
        await message.answer(f"Сохранено: {item_line(item)}")

    @router.callback_query(FCb.filter(F.a == "new"))
    async def new_item(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, FoodInput.new_name)
        await bot.send_message(query.from_user.id, "Название рецепта или продукта?",
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.message(StateFilter(FoodInput.new_name), F.text)
    async def new_name(message: Message, actor: Actor, state: FSMContext) -> None:
        name = " ".join((message.text or "").split())
        if not 1 <= len(name) <= 64:
            raise AppError("INPUT-TEXT", field="Название", low=1, high=64, length=len(name))
        if any(i.name.lower() == name.lower() for i in await food.items(actor, include_hidden=True)):
            raise AppError("INPUT-DUPLICATE", name=name)
        await state.update_data(name=name)
        await state.set_state(FoodInput.new_unit)
        token = await dialog_token(state)
        buttons = [fbtn(actor, token, label, "nu", unit) for unit, label in UNIT_BUTTONS.items()]
        await message.answer("Как записывать: порциями, на вес или в штуках?",
                             reply_markup=inline([buttons, [cancel(actor, token)]]))

    @router.callback_query(StateFilter(FoodInput.new_unit), FCb.filter(F.a == "nu"))
    async def new_unit(query: CallbackQuery, callback_data: FCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        unit = Unit(callback_data.v or Unit.PORTION.value)
        await state.update_data(unit=unit.value)
        await state.set_state(FoodInput.new_values)
        token = await dialog_token(state)
        await bot.send_message(query.from_user.id, VALUES_PROMPT.format(unit=UNIT_NAMES[unit]),
                               reply_markup=inline([[cancel(actor, token)]]))

    @router.message(StateFilter(FoodInput.new_values), F.text)
    async def new_values(message: Message, actor: Actor, state: FSMContext) -> None:
        nutrients, price = parse_values_line(message.text or "")
        data: dict[str, Any] = await state.get_data()
        unit = Unit(data["unit"])
        item = await food.create_item(actor, name=data["name"], kind=RECIPE if unit is Unit.PORTION else PRODUCT,
                                      unit=unit, nutrients=nutrients, price=price)
        await state.clear()
        trail.result()
        await message.answer(f"Добавлено: {item_line(item)}\nОно уже в списке «🍽 Еда».")

    return nav, router
