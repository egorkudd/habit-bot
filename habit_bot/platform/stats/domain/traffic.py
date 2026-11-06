"""Клетки обзора «Итогов» (раздел 4.10, правка 1.0.1): три оттенка вместо светофора.

* чёрная — цель дня выполнена (пороги раздела 4.10: калории ±10%, белки ≥ 90%, жиры и углеводы ±15%, зарядок и
  привычки — не меньше цели, вес — в сторону цели);
* серая — что-то записано, но цель не выполнена;
* белая — ничего не записано;
* «в» — выходной; бледная — не по расписанию или до анкеты; пустая — день ещё не наступил."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

WEIGHT_STILL = Decimal("0.2")  # «стоит на месте (±0,2 кг)»


class Color(StrEnum):
    DONE = "done"        # чёрная
    PARTIAL = "partial"  # серая
    NONE = "none"        # белая
    OFF = "off"          # выходной
    SKIP = "skip"        # не по расписанию, до анкеты — не оценивается
    FUTURE = "future"    # день ещё не наступил


RATED = (Color.DONE, Color.PARTIAL, Color.NONE)
ICON = {Color.DONE: "●", Color.PARTIAL: "◐", Color.NONE: "○", Color.OFF: "в", Color.SKIP: "·", Color.FUTURE: " "}
LEGEND = "● выполнено  ◐ частично  ○ ничего  в выходной"


def _level(done: bool, something: bool) -> Color:
    if done:
        return Color.DONE
    return Color.PARTIAL if something else Color.NONE


def _within(fact: Decimal, goal: Decimal, share: str) -> bool:
    return abs(fact - goal) / goal <= Decimal(share)


def kcal(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Калории: отклонение от цели ≤ 10% — выполнено."""
    if not fact:
        return Color.NONE
    return _level(goal is not None and goal > 0 and _within(fact, goal, "0.10"), True)


def macro(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Жиры и углеводы: отклонение ≤ 15% — выполнено."""
    if not fact:
        return Color.NONE
    return _level(goal is not None and goal > 0 and _within(fact, goal, "0.15"), True)


def protein(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Белки: ≥ 90% цели — выполнено (перебор белка — не ошибка)."""
    if not fact:
        return Color.NONE
    return _level(goal is not None and goal > 0 and fact >= goal * Decimal("0.9"), True)


def warmup(done: int, goal: int) -> Color:
    """Зарядка: выполнено ≥ цели в день — чёрная, хотя бы одна — серая, ни одной — белая."""
    return _level(done >= max(goal, 1), done > 0)


def weekly(count: int, goal: int) -> Color:
    """Тренировки за неделю: ≥ цели — выполнено."""
    return _level(count >= goal, count > 0)


def habit(fact: Decimal, goal: Decimal | None) -> Color:
    """Своя привычка: ≥ цели — выполнено, часть — серая; без цели — отметка есть или нет."""
    return _level(fact >= goal if goal is not None else fact > 0, fact > 0)


def weight(delta: Decimal | None, direction: int) -> Color:
    """Вес за неделю (средний к средней прошлой): в сторону цели (при поддержании — на месте, ±0,2 кг) —
    выполнено; иначе — серая; нет взвешиваний — белая. ``direction``: −1 — снижение, +1 — набор, 0 — поддержание."""
    if delta is None:
        return Color.NONE
    if direction == 0:
        return _level(abs(delta) <= WEIGHT_STILL, True)
    return _level(abs(delta) > WEIGHT_STILL and (delta > 0) == (direction > 0), True)


def percent(fact: Decimal, goal: Decimal | None) -> int | None:
    if not goal:
        return None
    return int((fact * 100 / goal).to_integral_value())


def green_share(cells: Sequence[Color]) -> int | None:
    """% выполненных дней среди оценённых (выходные, не по расписанию и будущее не считаются)."""
    rated = [c for c in cells if c in RATED]
    if not rated:
        return None
    return round(100 * sum(c is Color.DONE for c in rated) / len(rated))


def current_streak(cells: Sequence[Color]) -> int:
    """Выполненные подряд с конца; выходные, неоценённые и будущие дни серию не прерывают и не продлевают."""
    count = 0
    for cell in reversed(cells):
        if cell is Color.DONE:
            count += 1
        elif cell in (Color.PARTIAL, Color.NONE):
            break
    return count
