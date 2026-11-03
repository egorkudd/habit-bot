"""Цели КБЖУ (раздел 4.1): Миффлин — Сан Жеор, коэффициент активности, поправка на цель, БЖУ на кг веса.

Проверка на владельце: мужчина, 23 года, 178 см, 75 кг, лёгкая активность → базовый обмен 1752,5,
расход 2409,69 → набор: 2800 ккал / Б 160 / Ж 80 / У 360.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_number
from habit_bot.kernel.errors import AppError


class Sex(StrEnum):
    MALE = "male"
    FEMALE = "female"


class Activity(StrEnum):
    MINIMAL = "minimal"
    LIGHT = "light"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class GoalMode(StrEnum):
    GAIN = "gain"
    MAINTAIN = "maintain"
    LOSS = "loss"


class Experience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


ACTIVITY_FACTOR: dict[Activity, Decimal] = {
    Activity.MINIMAL: Decimal("1.2"),
    Activity.LIGHT: Decimal("1.375"),
    Activity.MEDIUM: Decimal("1.55"),
    Activity.HIGH: Decimal("1.725"),
    Activity.VERY_HIGH: Decimal("1.9"),
}
KCAL_SHIFT: dict[GoalMode, int] = {GoalMode.GAIN: 400, GoalMode.MAINTAIN: 0, GoalMode.LOSS: -500}
# Белки и жиры, г на кг веса (раздел 4.1); углеводы — остаток калорий / 4.
MACROS_PER_KG: dict[GoalMode, tuple[Decimal, Decimal]] = {
    GoalMode.GAIN: (Decimal("2.1"), Decimal("1.05")),
    GoalMode.MAINTAIN: (Decimal("1.8"), Decimal("0.95")),
    GoalMode.LOSS: (Decimal("2.2"), Decimal("0.9")),
}
LOSS_FLOOR: dict[Sex, int] = {Sex.MALE: 1500, Sex.FEMALE: 1200}
MIN_BMI_FOR_LOSS = Decimal("18.5")
LOW_CARBS = 100
MANUAL_KCAL = (1200, 6000)
MANUAL_TOLERANCE = Decimal("0.05")

WARN_LOSS_FLOOR = "Снижение ограничено: не ниже базового обмена и не ниже {floor} ккал в день."
WARN_LOW_CARBS = "Углеводов меньше 100 г — это мало для тренировок; можно поправить вручную."
WARN_MANUAL_MISMATCH = "По Б·4 + Ж·9 + У·4 выходит {computed} ккал, а указано {kcal} — разница больше 5%."


@dataclass(frozen=True, slots=True)
class BodyInputs:
    sex: Sex
    birth_date: date
    height_cm: Decimal
    weight_kg: Decimal
    activity: Activity
    mode: GoalMode


@dataclass(frozen=True, slots=True)
class Targets:
    kcal: int
    protein: int
    fat: int
    carbs: int
    bmr: Decimal = Decimal(0)
    tdee: Decimal = Decimal(0)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    def as_tuple(self) -> tuple[int, int, int, int]:
        return self.kcal, self.protein, self.fat, self.carbs


def age_on(birth_date: date, today: date) -> int:
    """Полных лет на дату."""
    before_birthday = (today.month, today.day) < (birth_date.month, birth_date.day)
    return today.year - birth_date.year - int(before_birthday)


def bmi(weight_kg: Decimal, height_cm: Decimal) -> Decimal:
    metres = height_cm / 100
    return (weight_kg / (metres * metres)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def allowed_modes(weight_kg: Decimal, height_cm: Decimal) -> list[GoalMode]:
    """Снижение веса недоступно при ИМТ < 18,5 (раздел 3.0, шаг 7)."""
    modes = [GoalMode.GAIN, GoalMode.MAINTAIN]
    if bmi(weight_kg, height_cm) >= MIN_BMI_FOR_LOSS:
        modes.append(GoalMode.LOSS)
    return modes


def basal_metabolism(sex: Sex, weight_kg: Decimal, height_cm: Decimal, age: int) -> Decimal:
    base = 10 * weight_kg + Decimal("6.25") * height_cm - 5 * age
    return base + (5 if sex is Sex.MALE else -161)


def _round_to(value: Decimal, step: int, rounding: str = ROUND_HALF_UP) -> int:
    return int((value / step).quantize(Decimal(1), rounding=rounding) * step)


def calculate_targets(inputs: BodyInputs, today: date) -> Targets:
    age = age_on(inputs.birth_date, today)
    bmr = basal_metabolism(inputs.sex, inputs.weight_kg, inputs.height_cm, age)
    tdee = bmr * ACTIVITY_FACTOR[inputs.activity]
    warnings: list[str] = []
    kcal_raw = tdee + KCAL_SHIFT[inputs.mode]
    kcal = _round_to(kcal_raw, 50)
    if inputs.mode is GoalMode.LOSS:
        floor = max(bmr, Decimal(LOSS_FLOOR[inputs.sex]))
        if kcal_raw < floor:
            kcal = _round_to(floor, 50, ROUND_CEILING)
            warnings.append(WARN_LOSS_FLOOR.format(floor=LOSS_FLOOR[inputs.sex]))
    protein_per_kg, fat_per_kg = MACROS_PER_KG[inputs.mode]
    protein = _round_to(protein_per_kg * inputs.weight_kg, 5)
    fat = _round_to(fat_per_kg * inputs.weight_kg, 5)
    carbs = max(0, _round_to(Decimal(kcal - protein * 4 - fat * 9) / 4, 5))
    if carbs < LOW_CARBS:
        warnings.append(WARN_LOW_CARBS)
    return Targets(
        kcal=kcal, protein=protein, fat=fat, carbs=carbs,
        bmr=bmr.quantize(Decimal("0.01")), tdee=tdee.quantize(Decimal("0.01")), warnings=tuple(warnings),
    )


def check_manual_targets(kcal: Decimal, protein: Decimal, fat: Decimal, carbs: Decimal) -> list[str]:
    """Ручные КБЖУ: ккал 1200–6000, Б/Ж/У ≥ 0; расхождение с Б·4 + Ж·9 + У·4 больше 5% — предупреждение."""
    low, high = MANUAL_KCAL
    if not low <= kcal <= high:
        raise AppError("INPUT-RANGE", field="Калории", low=low, high=high, unit=" ккал", value=format_number(kcal),
                       guess="")
    computed = protein * 4 + fat * 9 + carbs * 4
    if abs(computed - kcal) > kcal * MANUAL_TOLERANCE:
        return [WARN_MANUAL_MISMATCH.format(computed=format_number(computed), kcal=format_number(kcal))]
    return []


def check_target_weight(mode: GoalMode, current: Decimal, target: Decimal) -> None:
    """Целевой вес согласован с целью: набор — больше текущего, снижение — меньше, поддержание — ±5%."""
    if mode is GoalMode.GAIN:
        low, high, field_name = current + Decimal("0.5"), Decimal(250), "Целевой вес при наборе"
    elif mode is GoalMode.LOSS:
        low, high, field_name = Decimal(35), current - Decimal("0.5"), "Целевой вес при снижении"
    else:
        low, high = (current * Decimal("0.95")).quantize(Decimal("0.1")), (current * Decimal("1.05")).quantize(
            Decimal("0.1"))
        field_name = "Целевой вес при поддержании"
    if not low <= target <= high:
        raise AppError("INPUT-RANGE", field=field_name, low=format_number(low), high=format_number(high),
                       unit=" кг", value=format_number(target), guess="")
