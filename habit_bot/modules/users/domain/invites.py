"""Приглашения (раздел 3.0, 3.13): одноразовые или на N человек, со сроком; администратор может отозвать."""

from __future__ import annotations

from datetime import date, datetime

from habit_bot.kernel.domain.formatting import format_day
from habit_bot.kernel.errors import AppError

USES_CHOICES = (1, 3, 5, 10)
DAYS_CHOICES = (1, 7, 30, 0)  # 0 — без срока


def check_invite(
    *, max_uses: int, uses: int, expires_at: datetime | None, revoked_at: datetime | None, now: datetime,
    expires_local: date | None = None,
) -> None:
    """Ссылка больше не действует — ``ACCESS-INVITE-EXPIRED`` с причиной."""
    if revoked_at is not None:
        reason = "отозвана"
    elif expires_at is not None and now >= expires_at:
        reason = f"истекла {format_day(expires_local or expires_at.date())}"
    elif uses >= max_uses:
        reason = "все места уже заняты"
    else:
        return
    raise AppError("ACCESS-INVITE-EXPIRED", reason=reason)


def uses_label(max_uses: int) -> str:
    return "одноразовое" if max_uses == 1 else f"на {max_uses} человек"


def days_label(days: int) -> str:
    if days == 0:
        return "без срока"
    return f"{days} {'день' if days == 1 else 'дней'}"
