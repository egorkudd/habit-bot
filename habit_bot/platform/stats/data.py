"""Данные статистики отдельно от картинки (архитектура, 7.8): модули считают, канал рисует. Без ИИ и без сети."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from habit_bot.platform.stats.domain.traffic import Color


@dataclass(frozen=True, slots=True)
class Bar:
    """Полоса «факт / цель»: «Ккал ██████████▌ 105% 2 947 / 2 800 🟢»."""

    label: str
    fact: Decimal
    goal: Decimal | None
    color: Color
    unit: str = ""


@dataclass(frozen=True, slots=True)
class Table:
    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    right: tuple[int, ...] = ()  # номера столбцов с числами — по правому краю


@dataclass(frozen=True, slots=True)
class DayStats:
    """Картинка дня по одной привычке (раздел 3.8.1)."""

    title: str
    bars: tuple[Bar, ...] = ()
    tables: tuple[Table, ...] = ()
    lines: tuple[str, ...] = ()
    empty: bool = False


@dataclass(frozen=True, slots=True)
class TrafficRow:
    label: str
    cells: tuple[Color, ...]
    green: int | None
    streak: int


@dataclass(frozen=True, slots=True)
class Overview:
    """Обзор-светофор за период (раздел 3.8.2): строки — цели, столбцы — дни."""

    title: str
    days: tuple[date, ...]
    rows: tuple[TrafficRow, ...] = field(default_factory=tuple)
    today: date | None = None  # столбец сегодняшнего дня выделяется
