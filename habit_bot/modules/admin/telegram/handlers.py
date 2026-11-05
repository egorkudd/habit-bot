"""«🛠 Админ» в Telegram (раздел 3.13): «👥 Пользователи» (без содержимого дневника), блокировка, удаление,
«💰 Расходы на ИИ», «📚 Каталог» (добавить продукт, скрыть или вернуть)."""

from __future__ import annotations

from decimal import Decimal

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message

from habit_bot.channels.telegram.dialogs.fsm import start_dialog
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_date, format_day, format_number
from habit_bot.kernel.identity import Actor, Role, UserStatus
from habit_bot.modules.admin.usecases import Admin, UserRow
from habit_bot.modules.food.domain.other_line import parse_other_line

USERS_KEY, AI_KEY, CATALOG_KEY = "adm_users", "adm_ai", "adm_catalog"
PAGE = 10
PRODUCT_PROMPT = "➕ Название и КБЖУ на 1 порцию, например: Хлебец 35 1,2 0,4 6,9"
CATALOG_NOTE = "Изменения не трогают то, что пользователи уже добавили к себе."


class AdCb(CallbackData, prefix="ad"):
    o: int
    t: int
    a: str
    v: str = "-"  # пустая строка в данных кнопки возвращается как None


class AdminInput(StatesGroup):
    product = State()


def money(value: Decimal) -> str:
    """Доллары: копейки разборов видны как «< 0,01»."""
    return "< 0,01" if 0 < value < Decimal("0.01") else format_number(value)


def user_line(n: int, row: UserRow) -> str:
    marks = [row.name]
    if row.role is Role.ADMIN:
        marks.append("админ")
    if row.status is UserStatus.BLOCKED:
        marks.append("🔒 заблокирован")
    elif row.status is UserStatus.ONBOARDING:
        marks.append("анкета не пройдена")
    marks += [f"с {format_day(row.registered)}", f"активность {format_day(row.last_active)}",
              f"записей {row.records}"]
    return f"{n}. " + " · ".join(marks)


def build_admin_tools_router(admin: Admin, screens: Screens) -> Router:
    router = Router(name="admin")

    def btn(actor: Actor, text: str, action: str, value: str = "-") -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=AdCb(o=actor.user_id, t=0, a=action, v=value).pack())

    async def show_users(bot: Bot, chat_id: int, actor: Actor, prefix: str = "") -> None:
        rows = await admin.users(actor)
        text = f"👥 Пользователи: {len(rows)}\n" + "\n".join(user_line(i, r) for i, r in enumerate(rows, 1))
        buttons = [btn(actor, f"{i}. {r.name}"[:30], "user", str(r.user_id))
                   for i, r in enumerate(rows, 1) if not r.protected]
        await bot.send_message(chat_id, f"{prefix}\n\n{text}" if prefix else text,
                               reply_markup=inline(fit_rows(buttons, 2)) if buttons else None)

    async def show_user(bot: Bot, chat_id: int, actor: Actor, row: UserRow) -> None:
        status = {UserStatus.BLOCKED: "🔒 заблокирован", UserStatus.ONBOARDING: "анкета не пройдена"}.get(
            row.status, "активен")
        text = (f"👤 {row.name}\nС {format_date(row.registered)} · последняя активность {format_day(row.last_active)}"
                f" · записей {row.records}\nСтатус: {status}\nСодержимое дневника администратору не показывается.")
        block = btn(actor, "🔓 Разблокировать", "unblock", str(row.user_id)) if row.status is UserStatus.BLOCKED \
            else btn(actor, "🔒 Заблокировать", "block", str(row.user_id))
        rows = [[block, btn(actor, "🗑 Удалить", "del", str(row.user_id))], [btn(actor, "◀ К списку", "users")]]
        await bot.send_message(chat_id, text, reply_markup=inline(rows))

    def user_id(callback_data: AdCb) -> int:
        return int(callback_data.v) if callback_data.v.isdigit() else 0

    @router.callback_query(MenuCb.filter(F.k == USERS_KEY))
    async def open_users(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await show_users(bot, query.from_user.id, actor)

    @router.callback_query(AdCb.filter(F.a == "users"))
    async def back_to_users(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await show_users(bot, query.from_user.id, actor)

    @router.callback_query(AdCb.filter(F.a == "user"))
    async def open_user(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        row = await admin.user(actor, user_id(callback_data))
        if row is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        await show_user(bot, query.from_user.id, actor, row)

    @router.callback_query(AdCb.filter(F.a.in_({"block", "unblock"})))
    async def block(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        row = await admin.set_blocked(actor, user_id(callback_data), callback_data.a == "block")
        if row is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query, toast="Заблокирован" if callback_data.a == "block" else "Разблокирован")
        await show_user(bot, query.from_user.id, actor, row)

    @router.callback_query(AdCb.filter(F.a == "del"))
    async def ask_delete(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        row = await admin.user(actor, user_id(callback_data))
        if row is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await screens.close_buttons(query)
        await bot.send_message(query.from_user.id, f"Удалить «{row.name}» и все данные? Это нельзя отменить.",
                               reply_markup=inline([[btn(actor, "🗑 Да, удалить", "del_yes", str(row.user_id)),
                                                     btn(actor, "✕ Нет", "user", str(row.user_id))]]))

    @router.callback_query(AdCb.filter(F.a == "del_yes"))
    async def delete(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        deleted = await admin.delete_user(actor, user_id(callback_data))
        await screens.close_buttons(query)
        await show_users(bot, query.from_user.id, actor, "Пользователь удалён со всеми данными." if deleted
                         else "Уже удалён.")

    # --- расходы на ИИ ---
    @router.callback_query(MenuCb.filter(F.k == AI_KEY))
    async def ai_costs(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        costs = await admin.ai_costs(actor)
        lines = [f"💰 Расходы на ИИ за {costs.month}: {money(costs.total)} $ из {format_number(costs.budget)} $"]
        lines += [f"• {r.name} — разборов {r.parses} · {money(r.cost)} $" for r in costs.rows] or [
            "Разборов в этом месяце не было."]
        lines.append("Тексты запросов не хранятся дольше 30 дней и здесь не показываются.")
        await screens.home(bot, query.from_user.id, actor, "\n".join(lines))

    # --- каталог ---
    async def show_catalog(bot: Bot, chat_id: int, actor: Actor, prefix: str = "") -> None:
        products, hidden, exercises = await admin.catalog_counts(actor)
        text = (f"📚 Общий каталог\nПродуктов: {products} (скрыто {hidden}) · упражнений: {exercises}\n"
                f"{CATALOG_NOTE}")
        buttons = [[btn(actor, "➕ Продукт", "prod_new"), btn(actor, "🍽 Продукты", "prod_list", "0")]]
        await bot.send_message(chat_id, f"{prefix}\n\n{text}" if prefix else text, reply_markup=inline(buttons))

    @router.callback_query(MenuCb.filter(F.k == CATALOG_KEY))
    async def open_catalog(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await show_catalog(bot, query.from_user.id, actor)

    async def product_page(actor: Actor, page: int) -> tuple[str, list[list[InlineKeyboardButton]]]:
        items = await admin.food.catalog(include_hidden=True)
        pages = max(1, (len(items) + PAGE - 1) // PAGE)
        page = min(max(page, 0), pages - 1)
        shown = items[page * PAGE:(page + 1) * PAGE]
        lines = [f"🍽 Продукты каталога · страница {page + 1} из {pages}"]
        lines += [f"{i}. {item.name} — {format_number(item.nutrients.kcal)} ккал" + ("" if item.active else " · скрыт")
                  for i, item in enumerate(shown, page * PAGE + 1)]
        toggles = [btn(actor, f"{'🙈' if item.active else '👁'} {i}", "hide" if item.active else "show",
                       f"{item.public_id}_{page}") for i, item in enumerate(shown, page * PAGE + 1)]
        rows = fit_rows(toggles, 5)
        nav = []
        if page > 0:
            nav.append(btn(actor, "◀", "prod_list", str(page - 1)))
        if page + 1 < pages:
            nav.append(btn(actor, "▶", "prod_list", str(page + 1)))
        if nav:
            rows.append(nav)
        return "\n".join(lines) + "\n🙈 — скрыть для новых добавлений, 👁 — вернуть.", rows

    @router.callback_query(AdCb.filter(F.a == "prod_list"))
    async def list_products(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        text, rows = await product_page(actor, int(callback_data.v) if callback_data.v.isdigit() else 0)
        if isinstance(query.message, Message) and callback_data.v != "0":
            await query.answer()
            await query.message.edit_text(text, reply_markup=inline(rows))
            return
        await screens.close_buttons(query)
        await bot.send_message(query.from_user.id, text, reply_markup=inline(rows))

    @router.callback_query(AdCb.filter(F.a.in_({"hide", "show"})))
    async def toggle_product(query: CallbackQuery, callback_data: AdCb, bot: Bot, actor: Actor) -> None:
        await admin.catalog_counts(actor)  # проверка роли
        public_id, _, page = callback_data.v.partition("_")
        item = await admin.food.set_catalog_active(public_id, callback_data.a == "show")
        if item is None:
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return
        await query.answer("Скрыт" if callback_data.a == "hide" else "Возвращён")
        text, rows = await product_page(actor, int(page) if page.isdigit() else 0)
        if isinstance(query.message, Message):
            await query.message.edit_text(text, reply_markup=inline(rows))

    @router.callback_query(AdCb.filter(F.a == "prod_new"))
    async def new_product(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await admin.catalog_counts(actor)  # проверка роли
        await screens.close_buttons(query)
        token = await start_dialog(state, AdminInput.product)
        cancel = InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())
        await bot.send_message(query.from_user.id, PRODUCT_PROMPT, reply_markup=inline([[cancel]]))

    @router.message(StateFilter(AdminInput.product), F.text)
    async def product_typed(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await admin.catalog_counts(actor)  # проверка роли
        line = parse_other_line(message.text or "")  # ошибка — подсказка, ввод не сбрасывается
        item = await admin.food.add_catalog_item(line.name, line.nutrients)
        await state.clear()
        v = item.nutrients
        await show_catalog(bot, message.chat.id, actor,
                           f"✅ В каталоге: {item.name} — {format_number(v.kcal)} ккал · Б {format_number(v.protein)}"
                           f" · Ж {format_number(v.fat)} · У {format_number(v.carbs)} на порцию")

    return router


__all__ = ["AdCb", "build_admin_tools_router"]
