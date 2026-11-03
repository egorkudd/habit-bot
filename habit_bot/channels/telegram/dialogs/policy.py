"""Сколько живёт незаконченный ввод (раздел 3, «Сброс через 15 минут бездействия»; раздел 4.3)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType

DIALOG = "dialog"          # текущий ввод: выбор блюда, количества, черновик зарядки, правка записи…
OTHER_DAY = "other_day"    # режим «Другой день» (часть 4)
WORKOUT = "workout"        # идущая тренировка (часть 8): 3 часа
ONBOARDING = "onboarding"  # анкета регистрации (часть 3): продолжается с того же шага

IDLE_TIMEOUT = timedelta(minutes=15)
WORKOUT_TIMEOUT = timedelta(hours=3)

DEFAULT_TTL: Mapping[str, timedelta | None] = MappingProxyType({
    DIALOG: IDLE_TIMEOUT,
    OTHER_DAY: IDLE_TIMEOUT,
    WORKOUT: WORKOUT_TIMEOUT,
    ONBOARDING: None,
})


class InactivityPolicy:
    """Срок жизни по области. Неизвестная область сбрасывается как обычный ввод — через 15 минут."""

    def __init__(self, ttl: Mapping[str, timedelta | None] = DEFAULT_TTL) -> None:
        self._ttl = dict(ttl)

    def ttl_for(self, scope: str) -> timedelta | None:
        return self._ttl.get(scope, IDLE_TIMEOUT)

    def expiring_scopes(self) -> dict[str, timedelta]:
        return {scope: ttl for scope, ttl in self._ttl.items() if ttl is not None}

    def known_scopes(self) -> set[str]:
        return set(self._ttl)
