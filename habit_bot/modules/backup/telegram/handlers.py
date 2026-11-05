"""«🛠 Админ» → «💾 Бэкап» (раздел 3.13): когда был последний и «💾 Бэкап сейчас» — файл приходит сразу."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton

from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.channels.telegram.ui.layout import inline
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day, format_number
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.backup.usecases import MANUAL, BackupFile, Backups

KEY = "backup"
FAILED = "💾 Бэкап не удался — прошлая копия на сервере на месте. Подробности — в оповещении выше."
TOO_BIG = "💾 Бэкап {size} МБ — больше 50 МБ, Telegram такой файл не примет. Копия сохранена на сервере."


class BkCb(CallbackData, prefix="bk"):
    o: int
    t: int
    a: str


def caption(made: BackupFile, backups: Backups) -> str:
    local = made.made_at.astimezone(backups._tz)
    return (f"💾 Бэкап базы {format_day(local)} {local:%H:%M} · {format_number(made.size_mb)} МБ. "
            "Зашифрован паролем BACKUP_PASSWORD; расшифровка — README, раздел «Бэкапы».")


async def send_backup(bot: Bot, chat_id: int, made: BackupFile, backups: Backups) -> None:
    if not backups.fits_telegram(made):
        await bot.send_message(chat_id, TOO_BIG.format(size=format_number(made.size_mb)))
        return
    await bot.send_document(chat_id, BufferedInputFile(made.data, filename=made.filename),
                            caption=caption(made, backups))


def build_backup_router(backups: Backups, screens: Screens) -> Router:
    router = Router(name="backup")

    @router.callback_query(MenuCb.filter(F.k == KEY))
    async def open_backup(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        backups.require_admin(actor)
        await screens.close_buttons(query)
        last = await backups.last()
        if last is None:
            when = "Последний: ещё не было."
        else:
            local = last.at.astimezone(backups._tz)
            when = f"Последний: {format_day(local)} {local:%H:%M} · {format_number(last.size_kb)} КБ."
        text = (f"💾 Бэкап базы\n{when}\nПо расписанию — раз в 2 дня, файл приходит администраторам. На сервере "
                "хранится одна последняя копия.")
        button = InlineKeyboardButton(text="💾 Бэкап сейчас", callback_data=BkCb(o=actor.user_id, t=0, a="now").pack())
        await bot.send_message(query.from_user.id, text, reply_markup=inline([[button]]))

    @router.callback_query(BkCb.filter(F.a == "now"))
    async def backup_now(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        backups.require_admin(actor)
        await screens.close_buttons(query, toast="Делаю бэкап…")
        try:
            made = await backups.make(MANUAL)
        except AppError:  # оповещение BKP-BOT уже ушло администраторам
            await screens.home(bot, query.from_user.id, actor, FAILED)
            return
        trail.result()
        await send_backup(bot, query.from_user.id, made, backups)

    return router


__all__ = ["BkCb", "build_backup_router", "send_backup"]
