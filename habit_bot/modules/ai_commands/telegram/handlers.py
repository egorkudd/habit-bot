"""Команды текстом в Telegram (раздел 3.10, 3.12): любой текст, который не ответ в текущем вводе, и «✍️ Текстом» →
карточка «Понял так» с «✅ Выполнить всё», «✏️ Исправить», «Убрать N», «✕ Отмена»; вопрос с вариантами кнопками;
итог с «↩️ Отменить всё» (10 минут). Режим заполнения — до 4000 символов, группы и постраничный просмотр."""

from __future__ import annotations

import html
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from habit_bot.channels.telegram.dialogs.fsm import start_dialog
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.errors.catalog import user_message
from habit_bot.kernel.identity import Actor
from habit_bot.modules.ai_commands.planner import GROUPS
from habit_bot.modules.ai_commands.usecases import FILL, TEXT, CommandView, TextCommands, summary

TEXT_KEY = "text"
FILL_KEY = "fill"
PAGE = 10
TEXT_PROMPT = ("✍️ Напишите обычным текстом, что записать или исправить. Например: «вчера на обед 2 бедра, а коктейль "
               "сегодня удали», «глаза сделал 2 раза», «пробежал 5,2 км за 28:40». Ничего не запишу без "
               "подтверждения.")
FILL_PROMPT = ("✍️ Вставьте текстом то, что у вас уже есть: рецепты с КБЖУ и ценой, цели КБЖУ с датами, набор "
               "зарядки, свои привычки, личные цели — до 4000 символов, можно частями. Покажу, как понял, и запишу "
               "только после подтверждения.")
FIX_PROMPT = "✏️ Напишите, что поправить, — разберу заново с учётом прошлого."
DayCard = Callable[[Actor, date], Awaitable[str]]


class AiCb(CallbackData, prefix="ai"):
    o: int
    t: int
    a: str
    v: str


class AiInput(StatesGroup):
    text = State()     # после «✍️ Текстом»
    fill = State()     # «✍️ Заполнить с помощью ИИ»
    correct = State()  # «✏️ Исправить»


def card_text(view: CommandView, page: int = 0) -> str:
    """«Понял так: 1. ➕ 24.10 Еда: …»; в заполнении — группы и страница по 10 пунктов."""
    lines = ["Понял так:"]
    ops = list(view.ops)
    if view.mode == FILL and len(ops) > PAGE:
        groups = Counter(GROUPS.get(op["group"], op["group"]) for op in ops)
        lines.append(" · ".join(f"{g}: {n}" for g, n in groups.items()))
        pages = (len(ops) + PAGE - 1) // PAGE
        lines.append(f"Страница {page + 1} из {pages}")
    start = page * PAGE if view.mode == FILL else 0
    shown = ops[start: start + PAGE] if view.mode == FILL else ops
    lines += [f"{i}. {op['line']}" for i, op in enumerate(shown, start + 1)]
    if view.skipped:
        lines.append("")
        lines.append("Не выполню:")
        lines += [f"• {s}" for s in view.skipped]
    return "\n".join(lines)


def build_ai_router(commands: TextCommands, screens: Screens, day_card: Callable[[], DayCard | None],
                    save_recipe_button: Callable[[Actor, str, str], InlineKeyboardButton] | None = None,
                    ) -> tuple[Router, Router]:
    router = Router(name="ai_commands")

    def btn(actor: Actor, text: str, action: str, value: str) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=AiCb(o=actor.user_id, t=0, a=action, v=value).pack())

    def card_markup(actor: Actor, view: CommandView, page: int = 0) -> InlineKeyboardMarkup:
        cid = view.public_id
        rows = [[btn(actor, "✅ Выполнить всё", "run", cid), btn(actor, "✏️ Исправить", "fix", cid)]]
        ops = list(view.ops)
        start = page * PAGE if view.mode == FILL else 0
        visible = ops[start: start + PAGE] if view.mode == FILL else ops
        drops = [btn(actor, f"{'Пропустить' if op.get('duplicate') else 'Убрать'} {i}", "drop", f"{cid}_{i}")
                 for i, op in enumerate(visible, start + 1)] if len(ops) > 1 else []
        rows += fit_rows(drops, 4)
        if view.mode == FILL and len(ops) > PAGE:
            groups = list(dict.fromkeys(op["group"] for op in ops))
            rows += fit_rows([btn(actor, f"Убрать «{GROUPS.get(g, g)}»", "dropg", f"{cid}_{g}") for g in groups])
            pages = (len(ops) + PAGE - 1) // PAGE
            nav = []
            if page > 0:
                nav.append(btn(actor, "◀ Назад", "page", f"{cid}_{page - 1}"))
            if page + 1 < pages:
                nav.append(btn(actor, "Дальше ▶", "page", f"{cid}_{page + 1}"))
            if nav:
                rows.append(nav)
        rows.append([btn(actor, "✕ Отмена", "cancel", cid)])
        return inline(rows)

    async def show(bot: Bot, chat_id: int, actor: Actor, view: CommandView) -> None:
        if view.question and not view.ops:
            options = view.question["options"]
            rows = fit_rows([btn(actor, o, "ans", f"{view.public_id}_{i}") for i, o in enumerate(options)])
            rows.append([btn(actor, "✕ Отмена", "cancel", view.public_id)])
            await bot.send_message(chat_id, view.question["text"], reply_markup=inline(rows))
            return
        if not view.ops:  # всё отброшено при проверке
            await bot.send_message(chat_id, card_text(view).replace("Понял так:\n", "", 1).strip())
            return
        await bot.send_message(chat_id, card_text(view), reply_markup=card_markup(actor, view))

    async def parse(bot: Bot, chat_id: int, actor: Actor, text: str, mode: str,
                    previous: str | None = None) -> None:
        try:
            view = await commands.parse(actor, text, mode=mode, previous=previous)
        except AppError as err:
            await bot.send_message(chat_id, err.user_text())
            return
        await show(bot, chat_id, actor, view)

    # --- «✍️ Текстом» и «✍️ Заполнить с помощью ИИ» ---
    @router.callback_query(MenuCb.filter(F.k.in_({TEXT_KEY, FILL_KEY})))
    async def open_input(query: CallbackQuery, callback_data: MenuCb, bot: Bot, actor: Actor,
                         state: FSMContext) -> None:
        await screens.close_buttons(query)
        if not commands.available:
            await screens.home(bot, query.from_user.id, actor, user_message("LLM-OFF"))
            return
        fill = callback_data.k == FILL_KEY
        token = await start_dialog(state, AiInput.fill if fill else AiInput.text)
        cancel = InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())
        await bot.send_message(query.from_user.id, FILL_PROMPT if fill else TEXT_PROMPT,
                               reply_markup=inline([[cancel]]))

    @router.message(StateFilter(AiInput.text, AiInput.fill), F.text)
    async def typed(message: Message, bot: Bot, actor: Actor, state: FSMContext, raw_state: str | None) -> None:
        mode = FILL if raw_state == AiInput.fill.state else TEXT
        await state.clear()
        await parse(bot, message.chat.id, actor, message.text or "", mode)

    # --- карточка ---
    async def own(query: CallbackQuery, bot: Bot, actor: Actor, command_id: str) -> CommandView | None:
        view = await commands.command(actor, command_id)
        if view is None or view.status != "pending":
            await screens.refuse_button(bot, query, actor, "UI-STALE")
            return None
        return view

    def split(value: str) -> tuple[str, str]:
        command_id, _, rest = value.partition("_")
        return command_id, rest

    @router.callback_query(AiCb.filter(F.a == "run"))
    async def run(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        if await own(query, bot, actor, callback_data.v) is None:
            return
        await screens.close_buttons(query)
        executed = await commands.execute(actor, callback_data.v)
        if executed is None:
            return
        done = executed.done
        lines = ["Готово:", *[f"{i}. {line}" for i, line in enumerate(done.lines, 1)]]
        if done.failed:
            lines += ["", "Не получилось:", *[f"• {f}" for f in done.failed]]
        rows = [[btn(actor, "↩️ Отменить всё", "undo", callback_data.v)]]
        if save_recipe_button is not None:
            rows += [[save_recipe_button(actor, entry_id, name)] for entry_id, name in done.approx]
        render = day_card()
        card = ""
        if render is not None and executed.days:
            card = "\n" + await render(actor, executed.days[-1])
        if query.message is not None:
            trail.discard(query.message.message_id)
        trail.result()
        await bot.send_message(query.from_user.id, html.escape("\n".join(lines)) + card, parse_mode="HTML",
                               reply_markup=inline(rows))

    @router.callback_query(AiCb.filter(F.a == "undo"))
    async def undo(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        count = await commands.undo_all(actor, callback_data.v)
        if count is None:
            await screens.close_buttons(query, toast="Отменить можно только в течение 10 минут")
            return
        await screens.close_buttons(query)
        trail.result()
        await bot.send_message(query.from_user.id, f"↩️ Отменено, данные как было (действий: {count}).")

    @router.callback_query(AiCb.filter(F.a.in_({"drop", "dropg"})))
    async def drop(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        command_id, rest = split(callback_data.v)
        view = await own(query, bot, actor, command_id)
        if view is None:
            return
        if callback_data.a == "drop":
            indexes = [int(rest)] if rest.isdigit() else []
        else:
            indexes = [i for i, op in enumerate(view.ops, 1) if op["group"] == rest]
        updated = await commands.drop(actor, command_id, indexes)
        await query.answer()
        if updated is None or not updated.ops:
            await screens.close_buttons(query)
            await screens.home(bot, query.from_user.id, actor, "Все пункты убраны — ничего не записано.")
            return
        if isinstance(query.message, Message):
            await query.message.edit_text(card_text(updated), reply_markup=card_markup(actor, updated))

    @router.callback_query(AiCb.filter(F.a == "page"))
    async def page(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        command_id, rest = split(callback_data.v)
        view = await own(query, bot, actor, command_id)
        if view is None:
            return
        await query.answer()
        number = int(rest) if rest.isdigit() else 0
        if isinstance(query.message, Message):
            await query.message.edit_text(card_text(view, number), reply_markup=card_markup(actor, view, number))

    @router.callback_query(AiCb.filter(F.a == "cancel"))
    async def cancel(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        await commands.cancel(actor, callback_data.v)
        await screens.close_buttons(query)
        trail.clean()
        await screens.home(bot, query.from_user.id, actor, "Отменено, ничего не записано.")

    @router.callback_query(AiCb.filter(F.a == "fix"))
    async def fix(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor, state: FSMContext) -> None:
        if await own(query, bot, actor, callback_data.v) is None:
            return
        await screens.close_buttons(query)
        token = await start_dialog(state, AiInput.correct)
        await state.update_data(command=callback_data.v)
        cancel_button = InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())
        await bot.send_message(query.from_user.id, FIX_PROMPT, reply_markup=inline([[cancel_button]]))

    @router.message(StateFilter(AiInput.correct), F.text)
    async def corrected(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        command_id = (await state.get_data()).get("command", "")
        await state.clear()
        previous = await commands.command(actor, command_id)
        if previous is None:
            raise AppError("UI-STALE")
        await commands.cancel(actor, command_id)
        await parse(bot, message.chat.id, actor, f"{previous.text}\nУточнение: {message.text or ''}", previous.mode,
                    previous=summary(previous.ops))

    @router.callback_query(AiCb.filter(F.a == "ans"))
    async def answer(query: CallbackQuery, callback_data: AiCb, bot: Bot, actor: Actor) -> None:
        command_id, rest = split(callback_data.v)
        view = await own(query, bot, actor, command_id)
        if view is None or not view.question:
            return
        options = view.question["options"]
        index = int(rest) if rest.isdigit() and int(rest) < len(options) else 0
        await screens.close_buttons(query)
        await commands.cancel(actor, command_id)
        await parse(bot, query.from_user.id, actor,
                    f"{view.text}\nОтвет на вопрос «{view.question['text']}»: {options[index]}", view.mode)

    # --- любой текст, который не ответ в текущем вводе: отдельный роутер, последним перед «Не понял» — сначала все
    # состояния ввода модулей. Без ключа модели не срабатывает — отвечает обычная подсказка с меню ---
    free = Router(name="ai_free_text")

    @free.message(F.text, F.func(lambda m: commands.available and not (m.text or "").startswith("/")))
    async def free_text(message: Message, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await state.clear()
        await parse(bot, message.chat.id, actor, message.text or "", TEXT)

    return router, free


__all__ = ["AiCb", "build_ai_router", "card_text"]
