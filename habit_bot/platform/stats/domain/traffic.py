"""Светофор статистики (раздел 4.10): цвет клетки по факту и цели, % зелёных дней и текущая серия.

Серая клетка — нет данных, не по расписанию или «Выходной»; пустая — день ещё не наступил."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

WEIGHT_STILL = Decimal("0.2")  # «стоит на месте (±0,2 кг)»


class Color(StrEnum):
    GREEN = "green"
    YELLOW = "yellow"
    RED = "red"
    GRAY = "gray"    # нет данных, не по расписанию, выходной
    EMPTY = "empty"  # будущий день или неделя ещё не закончилась


ICON = {Color.GREEN: "●", Color.YELLOW: "▲", Color.RED: "✕", Color.GRAY: "·", Color.EMPTY: " "}
EMOJI = {Color.GREEN: "🟢", Color.YELLOW: "🟡", Color.RED: "🔴", Color.GRAY: "⚪", Color.EMPTY: "⚪"}


def _deviation(fact: Decimal, goal: Decimal) -> Decimal:
    return abs(fact - goal) / goal


def _by_deviation(fact: Decimal | None, goal: Decimal | None, green: str, yellow: str) -> Color:
    if fact is None or not goal:
        return Color.GRAY
    deviation = _deviation(fact, goal)
    if deviation <= Decimal(green):
        return Color.GREEN
    return Color.YELLOW if deviation <= Decimal(yellow) else Color.RED


def kcal(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Калории: отклонение от цели ≤ 10% — зелёный, 10–20% — жёлтый, больше — красный."""
    return _by_deviation(fact, goal, "0.10", "0.20")


def macro(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Жиры и углеводы: отклонение ≤ 15% — зелёный, 15–30% — жёлтый, больше — красный."""
    return _by_deviation(fact, goal, "0.15", "0.30")


def protein(fact: Decimal | None, goal: Decimal | None) -> Color:
    """Белки: ≥ 90% цели — зелёный, 75–90% — жёлтый, меньше — красный (перебор белка — не ошибка)."""
    if fact is None or not goal:
        return Color.GRAY
    share = fact / goal
    if share >= Decimal("0.9"):
        return Color.GREEN
    return Color.YELLOW if share >= Decimal("0.75") else Color.RED


def warmup(done: int, goal: int) -> Color:
    """Зарядка: выполнено ≥ цели в день — зелёный, хотя бы одна — жёлтый, ни одной — красный."""
    if done >= max(goal, 1):
        return Color.GREEN
    return Color.YELLOW if done > 0 else Color.RED


def weekly(count: int, goal: int) -> Color:
    """Тренировки за неделю: ≥ цели — зелёный, ≥ половины — жёлтый, меньше — красный."""
    if count >= goal:
        return Color.GREEN
    return Color.YELLOW if count * 2 >= goal else Color.RED


def habit(fact: Decimal, goal: Decimal | None) -> Color:
    """Своя привычка: ≥ цели — зелёный, ≥ 50% — жёлтый, меньше — красный; без цели — отметка есть или нет."""
    if goal is None:
        return Color.GREEN if fact > 0 else Color.RED
    if fact >= goal:
        return Color.GREEN
    return Color.YELLOW if fact * 2 >= goal else Color.RED


def weight(delta: Decimal | None, direction: int) -> Color:
    """Вес за неделю (средний к средней прошлой недели): в сторону цели — зелёный, ±0,2 кг — жёлтый, против —
    красный. ``direction``: −1 — снижение, +1 — набор, 0 — поддержание (там «на месте» — зелёный)."""
    if delta is None:
        return Color.GRAY
    if abs(delta) <= WEIGHT_STILL:
        return Color.GREEN if direction == 0 else Color.YELLOW
    if direction == 0:
        return Color.YELLOW
    return Color.GREEN if (delta > 0) == (direction > 0) else Color.RED


def percent(fact: Decimal, goal: Decimal | None) -> int | None:
    if not goal:
        return None
    return int((fact * 100 / goal).to_integral_value())


def green_share(cells: Sequence[Color]) -> int | None:
    """% зелёных среди дней с оценкой (серые и пустые не считаются)."""
    rated = [c for c in cells if c in (Color.GREEN, Color.YELLOW, Color.RED)]
    if not rated:
        return None
    return round(100 * sum(c is Color.GREEN for c in rated) / len(rated))


def current_streak(cells: Sequence[Color]) -> int:
    """Зелёные подряд с конца; серые и пустые дни серию не прерывают и не продлевают."""
    count = 0
    for cell in reversed(cells):
        if cell is Color.GREEN:
            count += 1
        elif cell in (Color.YELLOW, Color.RED):
            break
    return count
