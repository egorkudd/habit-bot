"""Главное меню и «Ещё» (раздел 3.1). Модули заменяют заглушки своими разделами (архитектура, раздел 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.channels.telegram.ui.layout import fit_rows, fits
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.identity import Actor


class Place(StrEnum):
    HOME = "home"   # клавиатура под полем ввода
    MORE = "more"   # кнопки под сообщением «Ещё»
    SETTINGS = "settings"  # кнопки в «⚙️ Настройки» от модулей («🍽 Рецепты и продукты»)
    ADMIN = "admin"        # кнопки в «🛠 Админ» от модулей («👥 Пользователи», «💾 Бэкап»)


MORE_KEY = "more"
HOME_LABEL = "🏠 Домой"  # всегда рядом с «Ещё»: выйти из ввода и убрать его сообщения из чата


@dataclass(frozen=True, slots=True)
class MenuEntry:
    key: str
    label: str
    order: int
    place: Place = Place.HOME
    admin_only: bool = False
    part: int | None = None   # в какой части плана (раздел 8.1) появится раздел; пока его нет — «скоро»
    ready: bool = False       # раздел уже обрабатывает свой модуль
    habit: bool = False       # встроенная привычка: убранная с главного экрана — только в «✅ Привычки», не в «Ещё»


DEFAULT_ENTRIES: tuple[MenuEntry, ...] = (
    MenuEntry("food", "🍽 Еда", 10, part=5, habit=True),
    MenuEntry("warmup", "🤸 Зарядка", 20, part=6, habit=True),
    MenuEntry("workout", "🏋️ Тренировка", 30, part=8, habit=True),
    MenuEntry("habits", "✅ Привычки", 40, part=7),
    MenuEntry("stats", "📊 Итоги", 50, part=10),
    MenuEntry(MORE_KEY, "☰ Ещё", 1000, ready=True),
    MenuEntry("other_day", "📅 Другой день", 10, Place.MORE, part=4),
    MenuEntry("records", "📋 Записи", 15, Place.MORE, part=4),
    MenuEntry("text", "✍️ Текстом", 20, Place.MORE, part=9),
    MenuEntry("day_off", "🛌 Выходной", 30, Place.MORE, part=4),
    MenuEntry("settings", "⚙️ Настройки", 40, Place.MORE, part=3),
    MenuEntry("admin", "🛠 Админ", 50, Place.MORE, admin_only=True, part=3),
)


RETURN_SUFFIX = "✕ Вернуться к сегодня"


def return_label(day: date) -> str:
    """Первая кнопка клавиатуры в режиме «Другой день»: «📅 23.10 ✕ Вернуться к сегодня»."""
    return f"📅 {format_day(day)} {RETURN_SUFFIX}"


def is_return_label(text: str | None) -> bool:
    return bool(text) and text.startswith("📅 ") and text.endswith(RETURN_SUFFIX)  # type: ignore[union-attr]


def soon_text(entry: MenuEntry) -> str:
    when = f"в части {entry.part}" if entry.part else "позже"
    return f"{entry.label} — скоро: раздел появится {when} плана."


class MenuRegistry:
    """До 8 кнопок по 2 в ряд (длинные — по одной); последний ряд — «🏠 Домой» и «☰ Ещё», их не скрыть.
    Разделы, убранные с главного экрана, остаются в «Ещё» (раздел 3.1); еда, зарядка и тренировка — привычки:
    их открывает «✅ Привычки», в «Ещё» их нет (правки 1.0.2)."""

    HOME_LIMIT = 8
    PER_ROW = 2

    def __init__(self, entries: tuple[MenuEntry, ...] = DEFAULT_ENTRIES) -> None:
        self._entries: dict[str, MenuEntry] = {}
        for entry in entries:
            self.add(entry)

    def add(self, entry: MenuEntry) -> None:
        """Модуль регистрирует свой раздел; запись с тем же ключом заменяется."""
        self._entries[entry.key] = entry

    def mark_ready(self, key: str) -> None:
        self._entries[key] = replace(self._entries[key], ready=True)

    def get(self, key: str) -> MenuEntry | None:
        return self._entries.get(key)

    def by_label(self, text: str | None) -> MenuEntry | None:
        if not text:
            return None
        clean = text.strip()
        return next((e for e in self._entries.values() if e.place is Place.HOME and e.label == clean), None)

    def entries(self, place: Place, actor: Actor, layout: Sequence[str] | None = None,
                extra: Sequence[MenuEntry] = ()) -> list[MenuEntry]:
        """Пункты места. ``layout`` — выбранные пользователем кнопки главного экрана в его порядке;
        ``extra`` — кнопки самого пользователя (свои привычки), они встают на экран только по ``layout``."""
        visible = [e for e in self._entries.values() if e.place is place and (actor.is_admin or not e.admin_only)]
        visible.sort(key=lambda e: (e.key == MORE_KEY, e.order))
        if place is Place.HOME and layout is not None:
            by_key = {e.key: e for e in [*visible, *extra]}
            chosen = [by_key[k] for k in dict.fromkeys(layout) if k in by_key and k != MORE_KEY]
            visible = [*chosen, by_key[MORE_KEY]]
        if place is Place.HOME and len(visible) > self.HOME_LIMIT:
            visible = [*visible[: self.HOME_LIMIT - 1], visible[-1]]
        return visible

    def choosable(self, actor: Actor, extra: Sequence[MenuEntry] = ()) -> list[MenuEntry]:
        """Что можно поставить на главный экран: всё, кроме «Ещё» (её скрыть нельзя), и свои привычки."""
        visible = [e for e in self._entries.values()
                   if e.place is Place.HOME and e.key != MORE_KEY and (actor.is_admin or not e.admin_only)]
        return [*sorted(visible, key=lambda e: e.order), *extra]

    def defaults(self, actor: Actor) -> list[str]:
        """Кнопки главного экрана по умолчанию — когда пользователь его ещё не настраивал."""
        return [e.key for e in self.choosable(actor)][: self.HOME_LIMIT - 1]

    def home_keyboard(
        self, actor: Actor, layout: Sequence[str] | None = None, other_day: date | None = None,
        extra: Sequence[MenuEntry] = (),
    ) -> ReplyKeyboardMarkup:
        entries = self.entries(Place.HOME, actor, layout, extra)
        chosen = [KeyboardButton(text=e.label) for e in entries if e.key != MORE_KEY]
        more = next(e for e in entries if e.key == MORE_KEY)
        last = [KeyboardButton(text=HOME_LABEL), KeyboardButton(text=more.label)]
        rows = fit_rows(chosen, self.PER_ROW)
        if rows and len(rows[-1]) == 1 and fits([rows[-1][0].text, *(b.text for b in last)]):
            rows[-1] += last  # одиночная кнопка встаёт третьей, если все три подписи помещаются
        else:
            rows.append(last)
        if other_day is not None:
            rows.insert(0, [KeyboardButton(text=return_label(other_day))])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

    def hidden(self, actor: Actor, layout: Sequence[str] | None) -> list[MenuEntry]:
        """Разделы главного экрана, которых на нём сейчас нет: их показывает «Ещё».
        Привычки (еда, зарядка, тренировка) — нет: они в «✅ Привычки»."""
        shown = {e.key for e in self.entries(Place.HOME, actor, layout)}
        return [e for e in self.choosable(actor) if e.key not in shown and not e.habit]

    def settings_buttons(self, actor: Actor, place: Place = Place.SETTINGS) -> list[InlineKeyboardButton]:
        return [InlineKeyboardButton(text=e.label, callback_data=MenuCb(o=actor.user_id, t=0, k=e.key).pack())
                for e in self.entries(place, actor)]

    def more_keyboard(self, actor: Actor, layout: Sequence[str] | None = None) -> InlineKeyboardMarkup:
        """Сначала разделы, убранные с главного экрана, затем пункты «Ещё»."""
        def button(e: MenuEntry) -> InlineKeyboardButton:
            return InlineKeyboardButton(text=e.label, callback_data=MenuCb(o=actor.user_id, t=0, k=e.key).pack())

        rows = fit_rows([button(e) for e in self.hidden(actor, layout)], self.PER_ROW)
        rows += fit_rows([button(e) for e in self.entries(Place.MORE, actor)], self.PER_ROW)
        return InlineKeyboardMarkup(inline_keyboard=rows)
