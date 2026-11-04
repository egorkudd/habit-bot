"""Главное меню и «Ещё» (раздел 3.1). Модули заменяют заглушки своими разделами (архитектура, раздел 6)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from habit_bot.channels.telegram.ui.callbacks import MenuCb
from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.identity import Actor


class Place(StrEnum):
    HOME = "home"   # клавиатура под полем ввода
    MORE = "more"   # кнопки под сообщением «Ещё»
    SETTINGS = "settings"  # кнопки в «⚙️ Настройки» от модулей («🍽 Рецепты и продукты»)


MORE_KEY = "more"


@dataclass(frozen=True, slots=True)
class MenuEntry:
    key: str
    label: str
    order: int
    place: Place = Place.HOME
    admin_only: bool = False
    part: int | None = None   # в какой части плана (раздел 8.1) появится раздел; пока его нет — «скоро»
    ready: bool = False       # раздел уже обрабатывает свой модуль


DEFAULT_ENTRIES: tuple[MenuEntry, ...] = (
    MenuEntry("food", "🍽 Еда", 10, part=5),
    MenuEntry("warmup", "🤸 Зарядка", 20, part=6),
    MenuEntry("workout", "🏋️ Тренировка", 30, part=8),
    MenuEntry("habits", "✅ Привычки", 40, part=7),
    MenuEntry("stats", "📊 Итоги", 50, part=10),
    MenuEntry(MORE_KEY, "☰ Ещё", 1000, ready=True),
    MenuEntry("other_day", "📅 Другой день", 10, Place.MORE, part=4),
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
    """До 8 кнопок по 2 в ряд; «Ещё» всегда последняя и не скрывается (раздел 3.1)."""

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

    def entries(self, place: Place, actor: Actor, layout: Sequence[str] | None = None) -> list[MenuEntry]:
        """Пункты места. ``layout`` — выбранные пользователем кнопки главного экрана в его порядке."""
        visible = [e for e in self._entries.values() if e.place is place and (actor.is_admin or not e.admin_only)]
        visible.sort(key=lambda e: (e.key == MORE_KEY, e.order))
        if place is Place.HOME and layout is not None:
            by_key = {e.key: e for e in visible}
            chosen = [by_key[k] for k in dict.fromkeys(layout) if k in by_key and k != MORE_KEY]
            visible = [*chosen, by_key[MORE_KEY]]
        if place is Place.HOME and len(visible) > self.HOME_LIMIT:
            visible = [*visible[: self.HOME_LIMIT - 1], visible[-1]]
        return visible

    def choosable(self, actor: Actor) -> list[MenuEntry]:
        """Что можно поставить на главный экран: всё, кроме «Ещё» (её скрыть нельзя)."""
        visible = [e for e in self._entries.values()
                   if e.place is Place.HOME and e.key != MORE_KEY and (actor.is_admin or not e.admin_only)]
        return sorted(visible, key=lambda e: e.order)

    def home_keyboard(
        self, actor: Actor, layout: Sequence[str] | None = None, other_day: date | None = None,
    ) -> ReplyKeyboardMarkup:
        labels = [KeyboardButton(text=e.label) for e in self.entries(Place.HOME, actor, layout)]
        rows = [labels[i : i + self.PER_ROW] for i in range(0, len(labels), self.PER_ROW)]
        if other_day is not None:
            rows.insert(0, [KeyboardButton(text=return_label(other_day))])
        return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True, is_persistent=True)

    def settings_buttons(self, actor: Actor) -> list[InlineKeyboardButton]:
        return [InlineKeyboardButton(text=e.label, callback_data=MenuCb(o=actor.user_id, t=0, k=e.key).pack())
                for e in self.entries(Place.SETTINGS, actor)]

    def more_keyboard(self, actor: Actor) -> InlineKeyboardMarkup:
        buttons = [
            InlineKeyboardButton(text=e.label, callback_data=MenuCb(o=actor.user_id, t=0, k=e.key).pack())
            for e in self.entries(Place.MORE, actor)
        ]
        rows = [buttons[i : i + self.PER_ROW] for i in range(0, len(buttons), self.PER_ROW)]
        return InlineKeyboardMarkup(inline_keyboard=rows)
