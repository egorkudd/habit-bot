"""Тренировки (раздел 3.4.0–3.4.1): поля базы упражнений, фильтры по месту и оборудованию, подходы и тоннаж.

Чистые функции: без базы, сети и Telegram.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_duration, format_number
from habit_bot.kernel.domain.parsing import PlainUnit, parse_duration, parse_number_in_range
from habit_bot.kernel.errors import AppError

MAX_SETS = 12
MAX_REPS = 200
MAX_SET_SECONDS = 3600
MAX_WEIGHT = Decimal(500)


class Kind(StrEnum):
    """Тип тренировки (раздел 3.4)."""

    GYM = "gym"
    OUTDOOR = "outdoor"
    FREE = "free"


KIND_LABELS = {Kind.GYM: "🏋️ Зал", Kind.OUTDOOR: "🌳 Площадка", Kind.FREE: "🧩 Свободная"}


class Place(StrEnum):
    GYM = "gym"
    OUTDOOR = "outdoor"
    ANY = "any"


class Equipment(StrEnum):
    BARBELL = "barbell"
    DUMBBELL = "dumbbell"
    MACHINE = "machine"
    CABLE = "cable"
    KETTLEBELL = "kettlebell"
    PULLUP_BAR = "pullup_bar"
    DIP_BARS = "dip_bars"
    LOW_BAR = "low_bar"
    WALL_BARS = "wall_bars"
    BENCH = "bench"
    MONKEY_BARS = "monkey_bars"
    BAND = "band"
    NONE = "none"


# Стандартный набор уличной площадки — «Чего-то нет?» исключает отсутствующее (раздел 3.4.0).
OUTDOOR_EQUIPMENT: dict[Equipment, str] = {
    Equipment.PULLUP_BAR: "Турник", Equipment.DIP_BARS: "Брусья", Equipment.LOW_BAR: "Низкая перекладина",
    Equipment.WALL_BARS: "Шведская стенка", Equipment.BENCH: "Лавка", Equipment.MONKEY_BARS: "Рукоход",
}


class Muscle(StrEnum):
    QUADS = "quads"
    HAMSTRINGS = "hamstrings"
    GLUTES = "glutes"
    CALVES = "calves"
    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    BICEPS = "biceps"
    TRICEPS = "triceps"
    FOREARMS = "forearms"
    CORE = "core"


class Movement(StrEnum):
    SQUAT = "squat"
    HINGE = "hinge"
    LUNGE = "lunge"
    H_PUSH = "h_push"
    V_PUSH = "v_push"
    H_PULL = "h_pull"
    V_PULL = "v_pull"
    CORE = "core"
    ISOLATION = "isolation"


class Difficulty(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


class Measure(StrEnum):
    WEIGHT_REPS = "weight_reps"
    REPS = "reps"
    TIME = "time"
    BAND_REPS = "band_reps"


MEASURE_LABELS = {Measure.WEIGHT_REPS: "Вес × повторы", Measure.REPS: "Повторы", Measure.TIME: "Время",
                  Measure.BAND_REPS: "Резина × повторы"}


class Suggest(StrEnum):
    ALL = "all"
    MEN = "m"
    WOMEN = "f"


class Group(StrEnum):
    """Группа «Все по группам» (раздел 6.1)."""

    LEGS = "legs"
    HINGE = "hinge"
    CHEST = "chest"
    BACK = "back"
    SHOULDERS = "shoulders"
    ARMS = "arms"
    CORE = "core"
    BAR = "bar"
    DIPS = "dips"
    BENCH = "bench"
    STANDING = "standing"
    BAND = "band"


GROUP_LABELS = {
    Group.LEGS: "Ноги", Group.HINGE: "Тяга бедром", Group.CHEST: "Грудь, жимы", Group.BACK: "Спина, тяги",
    Group.SHOULDERS: "Плечи", Group.ARMS: "Руки", Group.CORE: "Кор", Group.BAR: "Турник и перекладина",
    Group.DIPS: "Брусья", Group.BENCH: "Лавка и стенка", Group.STANDING: "Стоя, без инвентаря",
    Group.BAND: "С резиной",
}


class Band(StrEnum):
    LIGHT = "light"
    MEDIUM = "medium"
    HEAVY = "heavy"


BAND_LABELS = {Band.LIGHT: "лёгкая", Band.MEDIUM: "средняя", Band.HEAVY: "тяжёлая"}


@dataclass(frozen=True, slots=True)
class ExerciseSpec:
    """Упражнение базы со всеми полями раздела 3.4.1."""

    key: str
    name: str
    place: Place
    equipment: Equipment
    group: Group
    primary: Muscle
    secondary: tuple[Muscle, ...]
    movement: Movement
    compound: bool
    difficulty: Difficulty
    measure: Measure
    floor: bool = False          # лёжа на земле: на улице не предлагается
    suggest: Suggest = Suggest.ALL
    loaded: bool = False         # с дополнительным весом (рюкзак, пояс)
    easier: str | None = None
    harder: str | None = None
    weight_step: Decimal | None = None
    reps_low: int = 8
    reps_high: int = 12
    per_dumbbell: bool = False   # вес каждой гантели — тоннаж ×2


@dataclass(frozen=True, slots=True)
class Filters:
    """Что предлагать на этой тренировке."""

    kind: Kind
    band: bool = True
    missing: frozenset[Equipment] = field(default_factory=frozenset)
    sex: str | None = None       # «m» / «f» из профиля
    show_all: bool = False


def offered(e: ExerciseSpec, f: Filters) -> bool:
    """Предлагать ли упражнение (раздел 3.4.1): место, оборудование, резина, «лёжа на земле», отягощение, пол.

    Фильтр по полу влияет только на подбор: «Показывать все упражнения» его снимает.
    """
    if f.kind is Kind.GYM and e.place is Place.OUTDOOR:
        return False
    if f.kind is Kind.OUTDOOR:
        if e.place is Place.GYM or e.floor or e.loaded:
            return False
        if e.equipment is Equipment.BAND and not f.band:
            return False
    if e.equipment in f.missing:
        return False
    return f.show_all or e.suggest is Suggest.ALL or e.suggest.value == f.sex


@dataclass(frozen=True, slots=True)
class SetValue:
    """Один подход: вес (кг), повторы или секунды, резина."""

    reps: int | None = None
    seconds: int | None = None
    weight: Decimal | None = None
    band: Band | None = None


_TIMES = re.compile(r"^\s*(\d{1,2})\s*[×xх*]\s*(\S+)\s*$", re.IGNORECASE)


def parse_counts(text: str, *, seconds: bool = False) -> list[int]:
    """«4×8», «4x8», «4*8» — одинаково во всех подходах; «8 8 7 6» — по подходам. Для времени — «3×45», «1:00 50»."""
    raw = text.strip().replace(",", " ")
    match = _TIMES.match(raw)
    if match:
        sets = int(match.group(1))
        if not 1 <= sets <= MAX_SETS:
            raise AppError("INPUT-SETS", value=text.strip())
        return [_count(match.group(2), seconds, text)] * sets
    parts = raw.split()
    if not 1 <= len(parts) <= MAX_SETS:
        raise AppError("INPUT-SETS", value=text.strip())
    return [_count(p, seconds, text) for p in parts]


def _count(part: str, seconds: bool, original: str) -> int:
    if seconds:
        value = parse_duration(part, PlainUnit.SECONDS)
        high = MAX_SET_SECONDS
    else:
        if not part.isdigit():
            raise AppError("INPUT-SETS", value=original.strip())
        value, high = int(part), MAX_REPS
    if not 1 <= value <= high:
        raise AppError("INPUT-SETS", value=original.strip())
    return value


def parse_weight(text: str) -> Decimal:
    """Вес в кг: «110», «112,5», «112.5 кг»."""
    clean = text.strip().lower().removesuffix("кг").strip()
    return parse_number_in_range(clean, low=Decimal("0.5"), high=MAX_WEIGHT, field="Вес", unit="кг")


def step_weight(weight: Decimal, step: Decimal, direction: int) -> Decimal:
    """«−шаг» / «+шаг» от текущего веса; не ниже нуля."""
    return max(Decimal(0), weight + step * direction)


def tonnage(sets: Iterable[SetValue], per_dumbbell: bool = False) -> Decimal:
    """Тоннаж = Σ вес × повторы; «вес каждой гантели» — ×2 (раздел 9: 110 × 8 × 4 = 3520)."""
    total = sum((s.weight * s.reps for s in sets if s.weight is not None and s.reps), Decimal(0))
    return total * 2 if per_dumbbell else total


def kg(value: Decimal) -> str:
    return f"{format_number(value)} кг"


def format_sets(measure: Measure, sets: Sequence[SetValue], per_dumbbell: bool = False) -> str:
    """«110 кг 4×8», «110 кг 8, 8, 7», «2×20 кг 3×10», «4×12», «3×0:45», «средняя резина 3×15»."""
    if not sets:
        return "нет подходов"
    counts = [s.seconds if measure is Measure.TIME else s.reps for s in sets]
    shown = [format_duration(c or 0) if measure is Measure.TIME else str(c or 0) for c in counts]
    reps = f"{len(sets)}×{shown[0]}" if len(set(shown)) == 1 else ", ".join(shown)
    if measure is Measure.WEIGHT_REPS:
        weights = {s.weight for s in sets}
        if len(weights) == 1:
            weight = sets[0].weight or Decimal(0)
            label = f"2×{kg(weight)}" if per_dumbbell else kg(weight)
            return f"{label} {reps}"
        return ", ".join(f"{format_number(s.weight or 0)}×{s.reps}" for s in sets) + " кг"
    if measure is Measure.BAND_REPS:
        bands = {s.band for s in sets}
        band = BAND_LABELS[sets[0].band] if len(bands) == 1 and sets[0].band else "резина"
        return f"{band} {reps}"
    return reps


def week_start(day: date) -> date:
    """Неделя для цели «тренировок в неделю» — с понедельника."""
    return day - timedelta(days=day.weekday())


def duration_label(minutes: int) -> str:
    return f"{minutes} мин"
