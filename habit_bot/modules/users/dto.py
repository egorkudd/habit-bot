"""Данные сценариев модуля users — без Telegram, их же потом вернёт HTTP API."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from habit_bot.modules.users.domain.city import City
from habit_bot.modules.users.domain.kbju import Activity, Experience, GoalMode, Sex, Targets


@dataclass(frozen=True, slots=True)
class ProfileData:
    name: str
    sex: Sex
    birth_date: date
    height_cm: Decimal
    weight_kg: Decimal
    activity: Activity
    mode: GoalMode
    target_weight: Decimal | None
    experience: Experience
    city: City | None = None


@dataclass(frozen=True, slots=True)
class ProfileView:
    name: str
    sex: Sex
    birth_date: date
    age: int
    height_cm: Decimal
    weight_kg: Decimal
    activity: Activity
    mode: GoalMode
    target_weight: Decimal | None
    experience: Experience
    city: City | None
    timezone: str
    starter_kit: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class GoalView:
    start_date: date
    kcal: Decimal
    protein: Decimal
    fat: Decimal
    carbs: Decimal
    source: str
    mode: GoalMode | None = None
    target_weight: Decimal | None = None

    @staticmethod
    def of(targets: Targets, start_date: date, source: str, mode: GoalMode | None) -> GoalView:
        return GoalView(start_date, Decimal(targets.kcal), Decimal(targets.protein), Decimal(targets.fat),
                        Decimal(targets.carbs), source, mode)

    def values(self) -> tuple[Decimal, Decimal, Decimal, Decimal]:
        return self.kcal, self.protein, self.fat, self.carbs


@dataclass(frozen=True, slots=True)
class InviteView:
    public_id: str
    code: str
    max_uses: int
    uses: int
    expires_at: datetime | None
    expires_day: date | None


@dataclass(frozen=True, slots=True)
class CityLookup:
    """Итог поиска: один город — сохранить сразу; несколько — выбор с регионом; ничего — похожие варианты."""

    query: str
    city: City | None = None
    options: tuple[City, ...] = ()
    suggestions: tuple[City, ...] = ()
