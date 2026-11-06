"""«⚙️ Настройки» → «📦 Экспорт» (раздел 3.12): период → галочки таблиц → «📄 Файлами» или «🗜 Одним архивом».

Выбор хранится в самих кнопках (период и маска галочек) — экран переживает перезапуск бота."""

from __future__ import annotations

from datetime import date

from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaDocument,
    Message,
)

from habit_bot.channels.telegram.dialogs.fsm import start_dialog
from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import CancelCb, MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows, inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_date
from habit_bot.kernel.identity import Actor
from habit_bot.modules.export.domain.period import parse_range
from habit_bot.modules.export.usecases import Export, ExportFile

KEY = "export"
PERIOD_TITLE = "📦 Экспорт своих данных в CSV — для таблиц и нейросетей. За какой период?"
DATES_PROMPT = "📅 Напишите две даты через тире: 01.10–22.10"
CHOOSE_TITLE = "📦 Экспорт за {period}. Отметьте, что выгрузить:"
NOTHING_CHOSEN = "Отметьте хотя бы одну таблицу"
SENT = "✅ Экспорт за {period}: {files}. Имени и Telegram-ID в файлах нет."
PERIODS = (("w", "Неделя"), ("m", "Месяц"), ("q", "3 месяца"), ("a", "Всё время"))


class ExCb(CallbackData, prefix="ex"):
    o: int
    t: int
    a: str
    p: str        # период: w / m / q / a или d + ггммдд + ггммдд
    m: int = 0    # галочки — битовая маска по порядку таблиц


class ExportInput(StatesGroup):
    dates = State()


def _code(day: date) -> str:
    return f"{day:%y%m%d}"


def _day(code: str) -> date:
    return date(2000 + int(code[:2]), int(code[2:4]), int(code[4:6]))


def files_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} файл"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} файла"
    return f"{n} файлов"


def build_export_router(export: Export, screens: Screens) -> Router:
    router = Router(name="export")

    def btn(actor: Actor, text: str, action: str, period: str, mask: int = 0) -> InlineKeyboardButton:
        return InlineKeyboardButton(text=text, callback_data=ExCb(o=actor.user_id, t=0, a=action, p=period,
                                                                    m=mask).pack())

    def resolve(period: str) -> tuple[date, date]:
        if period.startswith("d") and len(period) == 13:
            try:
                return _day(period[1:7]), _day(period[7:13])
            except ValueError:
                pass
        return export.period(period)

    def label(period: str) -> str:
        start, end = resolve(period)
        return "всё время" if period == "a" else f"{format_date(start)}–{format_date(end)}"

    def all_mask() -> int:
        return (1 << len(export.available())) - 1

    def choose_markup(actor: Actor, period: str, mask: int) -> InlineKeyboardMarkup:
        specs = export.available()
        boxes = [btn(actor, ("✅ " if mask >> i & 1 else "▫️ ") + spec.title, "tog", period, mask ^ (1 << i))
                 for i, spec in enumerate(specs)]
        rows = fit_rows(boxes, 2)
        rows.append([btn(actor, "📄 Файлами", "files", period, mask),
                     btn(actor, "🗜 Одним архивом", "zip", period, mask)])
        rows.append([btn(actor, "✕ Отмена", "cancel", period)])
        return inline(rows)

    async def open_export(bot: Bot, chat_id: int, actor: Actor) -> None:
        rows = fit_rows([btn(actor, text, "per", code) for code, text in PERIODS], 2)
        rows.append([btn(actor, "📅 Выбрать даты", "dates", "a"), btn(actor, "✕ Отмена", "cancel", "a")])
        await bot.send_message(chat_id, PERIOD_TITLE, reply_markup=inline(rows))

    @router.callback_query(MenuCb.filter(F.k == KEY))
    async def start(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        await state.clear()  # «Сначала скачать экспорт» из удаления аккаунта закрывает тот вопрос
        await open_export(bot, query.from_user.id, actor)

    @router.callback_query(ExCb.filter(F.a == "per"))
    async def period_chosen(query: CallbackQuery, callback_data: ExCb, actor: Actor) -> None:
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.edit_text(CHOOSE_TITLE.format(period=label(callback_data.p)),
                                          reply_markup=choose_markup(actor, callback_data.p, all_mask()))

    @router.callback_query(ExCb.filter(F.a == "tog"))
    async def toggle(query: CallbackQuery, callback_data: ExCb, actor: Actor) -> None:
        await query.answer()
        if isinstance(query.message, Message):
            await query.message.edit_reply_markup(reply_markup=choose_markup(actor, callback_data.p, callback_data.m))

    @router.callback_query(ExCb.filter(F.a == "dates"))
    async def dates(query: CallbackQuery, bot: Bot, actor: Actor, state: FSMContext) -> None:
        await screens.close_buttons(query)
        token = await start_dialog(state, ExportInput.dates)
        cancel = InlineKeyboardButton(text="✕ Отмена", callback_data=CancelCb(o=actor.user_id, t=token).pack())
        await bot.send_message(query.from_user.id, DATES_PROMPT, reply_markup=inline([[cancel]]))

    @router.message(StateFilter(ExportInput.dates), F.text)
    async def dates_typed(message: Message, actor: Actor, state: FSMContext) -> None:
        start, end = parse_range(message.text or "", export.today())  # ошибка — подсказка, ввод не сбрасывается
        await state.clear()
        period = f"d{_code(start)}{_code(end)}"
        await message.answer(CHOOSE_TITLE.format(period=label(period)),
                             reply_markup=choose_markup(actor, period, all_mask()))

    @router.callback_query(ExCb.filter(F.a == "cancel"))
    async def cancel(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await screens.home(bot, query.from_user.id, actor, "Отменено, ничего не выгружено.")

    @router.callback_query(ExCb.filter(F.a.in_({"files", "zip"})))
    async def send(query: CallbackQuery, callback_data: ExCb, bot: Bot, actor: Actor) -> None:
        keys = {spec.key for i, spec in enumerate(export.available()) if callback_data.m >> i & 1}
        if not keys:
            await query.answer(NOTHING_CHOSEN)
            return
        await screens.close_buttons(query)
        start, end = resolve(callback_data.p)
        files = await export.build(actor, start, end, keys)
        chat_id = query.from_user.id
        if callback_data.a == "zip":
            files = [export.archive(files)]
        await deliver(bot, chat_id, files)
        trail.result()
        count = "архив ZIP" if callback_data.a == "zip" else files_word(len(files))
        await screens.home(bot, chat_id, actor, SENT.format(period=label(callback_data.p), files=count))

    async def deliver(bot: Bot, chat_id: int, files: list[ExportFile]) -> None:
        """Один файл — документом, несколько — группой до 10 (так Telegram показывает их вместе)."""
        documents = [BufferedInputFile(f.data, filename=f.filename) for f in files]
        if len(documents) == 1:
            await bot.send_document(chat_id, documents[0])
            return
        for i in range(0, len(documents), 10):
            group = documents[i:i + 10]
            if len(group) == 1:
                await bot.send_document(chat_id, group[0])
            else:
                await bot.send_media_group(chat_id, [InputMediaDocument(media=d) for d in group])

    return router


__all__ = ["ExCb", "build_export_router"]
