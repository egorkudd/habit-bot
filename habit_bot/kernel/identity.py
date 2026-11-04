"""Пользователь и способы входа (раздел 5, сущности User и Identity).

Telegram-ID хранится только в ``Identity``: позже к тому же аккаунту добавится вход из приложения.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from habit_bot.kernel.db import Base, PublicIdMixin, TimestampMixin, UtcDateTime, VersionedMixin, utcnow


class Role(StrEnum):
    ADMIN = "admin"
    USER = "user"


class UserStatus(StrEnum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETED = "deleted"  # аккаунт удалён: строки пользователя стёрты, осталась обезличенная отметка


class Provider(StrEnum):
    TELEGRAM = "telegram"


def _enum(cls: type[StrEnum]) -> Enum:
    return Enum(cls, native_enum=False, length=16, values_callable=lambda e: [m.value for m in e])


class User(PublicIdMixin, TimestampMixin, VersionedMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[Role] = mapped_column(_enum(Role), nullable=False, default=Role.USER)
    status: Mapped[UserStatus] = mapped_column(_enum(UserStatus), nullable=False, default=UserStatus.ONBOARDING)
    invite_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_active_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    identities: Mapped[list[Identity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True,
    )


class Identity(Base):
    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_identities_provider_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[Provider] = mapped_column(_enum(Provider), nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=utcnow)

    user: Mapped[User] = relationship(back_populates="identities")


@dataclass(frozen=True, slots=True)
class Actor:
    """Кто действует: передаётся в каждый сценарий вместо объектов Telegram."""

    user_id: int
    role: Role
    channel: str
    request_time: datetime
    onboarding: bool = False  # анкета ещё не пройдена

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN
