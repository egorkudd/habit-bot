"""«Админ» → «Приглашения» (раздел 3.13): создать (одноразовое или на N человек, со сроком), список, отозвать."""

from __future__ import annotations

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from habit_bot.channels.telegram.ui import trail
from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows
from habit_bot.channels.telegram.ui.menu import Place
from habit_bot.channels.telegram.ui.screens import Screens
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.identity import Actor
from habit_bot.modules.users.domain.invites import DAYS_CHOICES, USES_CHOICES, days_label, uses_label
from habit_bot.modules.users.dto import InviteView
from habit_bot.modules.users.telegram.fields import UCb, button, keyboard
from habit_bot.modules.users.usecases import Invites

ADMIN_TITLE = "🛠 Админ"
NO_INVITES = "Действующих приглашений нет."


def invite_line(number: int, invite: InviteView) -> str:
    until = f"до {format_day(invite.expires_day)}" if invite.expires_day else "без срока"
    return f"{number}. {uses_label(invite.max_uses)} · использовано {invite.uses}/{invite.max_uses} · {until}"


async def invite_link(bot: Bot, code: str) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start={code}"


def build_admin_router(invites: Invites, screens: Screens) -> Router:
    router = Router(name="users.admin")

    async def show_invites(bot: Bot, chat_id: int, actor: Actor, prefix: str = "") -> None:
        active = await invites.active(actor)
        lines = [invite_line(i, inv) for i, inv in enumerate(active, start=1)] or [NO_INVITES]
        text = "🎟 Приглашения\n" + "\n".join(lines)
        if prefix:
            text = f"{prefix}\n\n{text}"
        rows = [[button(actor, 0, f"✕ Отозвать {i}", "inv_rv", inv.public_id)] for i, inv in enumerate(active, 1)]
        rows.append([button(actor, 0, "➕ Новое приглашение", "inv_new")])
        await bot.send_message(chat_id, text, reply_markup=keyboard(rows))

    @router.callback_query(MenuCb.filter(F.k == "admin"))
    async def open_admin(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await invites.active(actor)  # проверка роли до показа кнопок
        buttons = [button(actor, 0, "🎟 Приглашения", "inv_list"), *screens.menu.settings_buttons(actor, Place.ADMIN)]
        await bot.send_message(query.from_user.id, ADMIN_TITLE, reply_markup=keyboard(fit_rows(buttons, 2)))

    @router.callback_query(UCb.filter(F.a == "inv_list"))
    async def list_invites(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await show_invites(bot, query.from_user.id, actor)

    @router.callback_query(UCb.filter(F.a == "inv_new"))
    async def ask_uses(query: CallbackQuery, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        await invites.active(actor)  # проверка роли до показа кнопок
        row = [button(actor, 0, str(n), "inv_uses", str(n)) for n in USES_CHOICES]
        await bot.send_message(query.from_user.id, "Сколько человек сможет войти по ссылке?",
                               reply_markup=keyboard([row]))

    @router.callback_query(UCb.filter(F.a == "inv_uses"))
    async def ask_days(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        uses = int(callback_data.value) if callback_data.value.isdigit() else 1
        row = [button(actor, 0, days_label(d), "inv_days", f"{uses}_{d}") for d in DAYS_CHOICES]
        await bot.send_message(query.from_user.id, "Срок действия ссылки?", reply_markup=keyboard([row[:2], row[2:]]))

    @router.callback_query(UCb.filter(F.a == "inv_days"))
    async def create(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor) -> None:
        await screens.close_buttons(query)
        uses_text, _, days_text = callback_data.value.partition("_")
        uses = int(uses_text) if uses_text.isdigit() else 1
        days = int(days_text) if days_text.isdigit() else 0
        invite = await invites.create(actor, max_uses=uses, days=days)
        until = f"до {format_day(invite.expires_day)}" if invite.expires_day else "без срока"
        link = await invite_link(bot, invite.code)
        trail.result()  # ссылка остаётся в чате, чтобы её переслать
        await show_invites(
            bot, query.from_user.id, actor,
            f"Приглашение готово ({uses_label(uses)}, {until}). Перешлите ссылку тому, кого приглашаете:\n{link}",
        )

    @router.callback_query(UCb.filter(F.a == "inv_rv"))
    async def revoke(query: CallbackQuery, callback_data: UCb, bot: Bot, actor: Actor) -> None:
        revoked = await invites.revoke(actor, callback_data.value)
        await screens.close_buttons(query, toast="Приглашение отозвано" if revoked else "Уже не действует")
        await show_invites(bot, query.from_user.id, actor)

    return router
