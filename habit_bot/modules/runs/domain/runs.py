"""Бег (раздел 3.5, 4.9): темп, скорость, группы дистанций, рекорды, проверка нереального темпа. Чистые функции.

Темп = время / дистанция, округление до секунды, «м:сс мин/км»; скорость = дистанция / время в часах, 2 знака.
Пример раздела 9: 5,2 км за 28:40 → темп 5:31 мин/км, скорость 10,88 км/ч.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from habit_bot.kernel.domain.formatting import format_duration, format_number
from habit_bot.kernel.domain.parsing import PlainUnit, parse_duration, parse_number_in_range

FASTEST_PACE = 150   # 2:30 мин/км — быстрее переспросить
SLOWEST_PACE = 900   # 15:00 мин/км — медленнее переспросить
MAX_DISTANCE = Decimal(300)
QUICK_DISTANCES = (Decimal(3), Decimal(5), Decimal(10))


class DistanceGroup(StrEnum):
    SHORT = "до 5 км"
    MIDDLE = "5–10 км"
    LONG = "10 км и больше"


def parse_distance(text: str) -> Decimal:
    """«5.2», «5,2», «5,2 км»."""
    clean = text.strip().lower().removesuffix("км").strip()
    return parse_number_in_range(clean, low=Decimal("0.1"), high=MAX_DISTANCE, field="Дистанция", unit="км")


def parse_run_time(text: str) -> int:
    """«28:40», «28.40», «1:05:10» или «28» (целые минуты) → секунды."""
    return parse_duration(text, PlainUnit.MINUTES)


def pace(distance_km: Decimal, seconds: int) -> int:
    """Секунд на километр, округление до секунды."""
    return int((Decimal(seconds) / distance_km).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def speed(distance_km: Decimal, seconds: int) -> Decimal:
    """км/ч, 2 знака."""
    return (distance_km * 3600 / Decimal(seconds)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def suspicious(pace_sec: int) -> bool:
    """Темп быстрее 2:30 или медленнее 15:00 мин/км — переспросить «Всё верно?»."""
    return pace_sec < FASTEST_PACE or pace_sec > SLOWEST_PACE


def group_of(distance_km: Decimal) -> DistanceGroup:
    if distance_km < 5:
        return DistanceGroup.SHORT
    if distance_km < 10:
        return DistanceGroup.MIDDLE
    return DistanceGroup.LONG


def km(distance_km: Decimal) -> str:
    """«5,2 км», «5,0 км» — целое с «,0», как в требованиях."""
    if distance_km == distance_km.to_integral_value():
        return f"{int(distance_km)},0 км"
    return f"{format_number(distance_km)} км"


@dataclass(frozen=True, slots=True)
class RunValue:
    distance_km: Decimal
    seconds: int

    @property
    def pace(self) -> int:
        return pace(self.distance_km, self.seconds)


def comparison(current: RunValue, previous: RunValue | None) -> str:
    """«▲ на 0:09 быстрее прошлого» / «▼ на 0:05 медленнее прошлого» / «= как в прошлый раз» — по темпу,
    с прошлым забегом той же группы дистанций."""
    if previous is None:
        return "первый забег в группе «" + group_of(current.distance_km).value + "»"
    delta = previous.pace - current.pace
    if delta > 0:
        return f"▲ на {format_duration(delta)} быстрее прошлого"
    if delta < 0:
        return f"▼ на {format_duration(-delta)} медленнее прошлого"
    return "= темп как в прошлый раз"


def records(current: RunValue, history: Sequence[RunValue]) -> list[str]:
    """Рекорды (раздел 3.5): самая длинная дистанция; лучший темп в своей группе дистанций."""
    found = []
    if history and current.distance_km > max(r.distance_km for r in history):
        found.append(f"🏆 Самая длинная дистанция: {km(current.distance_km)}")
    group = group_of(current.distance_km)
    same = [r.pace for r in history if group_of(r.distance_km) is group]
    if same and current.pace < min(same):
        found.append(f"🏆 Лучший темп {group.value}: {format_duration(current.pace)}")
    return found


def run_line(value: RunValue) -> str:
    """«🏃 5,2 км · 28:40 · темп 5:31 · 10,88 км/ч»."""
    return (f"🏃 {km(value.distance_km)} · {format_duration(value.seconds)} · темп {format_duration(value.pace)} · "
            f"{format_number(speed(value.distance_km, value.seconds))} км/ч")
