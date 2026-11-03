"""Защита от повторов (раздел 7, «Повторы запросов»).

Повтор действия с тем же ключом не создаёт дубль и возвращает прежний результат. Ключи хранятся 24 часа.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint, delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from habit_bot.kernel.db import Base, UtcDateTime

KEY_TTL = timedelta(hours=24)


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("user_id", "request_id", name="uq_idempotency_keys_user_id_request_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, index=True)


class IdempotencyStore:
    async def run_once(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        request_id: str,
        now: datetime,
        action: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        """Выполняет ``action`` один раз на пару (пользователь, ключ) в течение 24 часов.

        Должно вызываться внутри транзакции сценария: ключ сохраняется вместе с изменениями.
        """
        existing = await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.request_id == request_id,
                IdempotencyKey.created_at > now - KEY_TTL,
            )
        )
        found = existing.scalar_one_or_none()
        if found is not None:
            return dict(found.result)
        await session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.request_id == request_id)
        )
        result = await action()
        session.add(IdempotencyKey(user_id=user_id, request_id=request_id, result=result, created_at=now))
        await session.flush()
        return result

    async def purge(self, session: AsyncSession, now: datetime) -> int:
        """Удаляет ключи старше 24 часов; возвращает число удалённых."""
        result = await session.execute(delete(IdempotencyKey).where(IdempotencyKey.created_at <= now - KEY_TTL))
        return int(getattr(result, "rowcount", 0) or 0)
