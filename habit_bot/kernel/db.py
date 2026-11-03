"""База данных: SQLite в режиме WAL, схема совместима с PostgreSQL (раздел 7).

Общие служебные поля (раздел 5): ``public_id``, ``created_at``, ``updated_at``,
у записей — ``deleted_at``, у редактируемых сущностей — ``version``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Any, ClassVar, Generic, TypeVar

from sqlalchemy import DateTime, MetaData, Uuid, event, select
from sqlalchemy.engine import Engine
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import TypeDecorator

from habit_bot.kernel.events import DomainEvent, EventBus

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """Время всегда хранится в UTC и возвращается с часовым поясом (SQLite сам пояс не хранит)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("В базу можно записывать только время с часовым поясом")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Any) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


class PublicIdMixin:
    """Внешний ID (UUID) для кнопок и будущего API вместо порядкового номера."""

    public_id: Mapped[uuid.UUID] = mapped_column(Uuid, default=uuid.uuid4, unique=True, nullable=False)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SoftDeleteMixin:
    """Удалённая запись не видна в боте, но 30 дней хранится как отметка для синхронизации."""

    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


class VersionedMixin:
    """Оптимистическая блокировка: правка устаревшей версии объекта не перезапишет чужие изменения."""

    version: Mapped[int] = mapped_column(nullable=False, default=1)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


def install_sqlite_pragmas(engine: Engine) -> None:
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _sqlite_pragmas)


def make_engine(url: str) -> AsyncEngine:
    engine = create_async_engine(url)
    install_sqlite_pragmas(engine.sync_engine)
    return engine


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


class UnitOfWork:
    """Одно действие пользователя — одна транзакция. События уходят подписчикам после commit."""

    session: AsyncSession

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession], events: EventBus) -> None:
        self._sessionmaker = sessionmaker
        self._events = events
        self._pending: list[DomainEvent] = []

    async def __aenter__(self) -> UnitOfWork:
        self.session = self._sessionmaker()
        self._pending = []
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: Any) -> None:
        try:
            if exc_type is None:
                await self.session.commit()
            else:
                await self.session.rollback()
        finally:
            await self.session.close()
        if exc_type is None:
            pending, self._pending = self._pending, []
            for item in pending:
                await self._events.publish(item)

    def collect(self, item: DomainEvent) -> None:
        self._pending.append(item)


UowFactory = Callable[[], UnitOfWork]

T = TypeVar("T", bound=Base)


class UserScopedRepository(Generic[T]):
    """Доступ к данным одного пользователя (раздел 4.4): без ``user_id`` запрос не построить."""

    model: ClassVar[type[Base]]

    def __init__(self, session: AsyncSession, user_id: int) -> None:
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise ValueError("Репозиторий пользовательских данных требует user_id")
        self.session = session
        self.user_id = user_id

    def _scope(self) -> list[ColumnElement[bool]]:
        model: Any = self.model
        conditions: list[ColumnElement[bool]] = [model.user_id == self.user_id]
        if hasattr(model, "deleted_at"):
            conditions.append(model.deleted_at.is_(None))
        return conditions

    async def get(self, item_id: int) -> T | None:
        model: Any = self.model
        result = await self.session.execute(select(model).where(model.id == item_id, *self._scope()))
        return result.scalar_one_or_none()  # type: ignore[no-any-return, unused-ignore]

    async def find(self, *where: ColumnElement[bool]) -> Sequence[T]:
        result = await self.session.execute(select(self.model).where(*self._scope(), *where))
        return result.scalars().all()  # type: ignore[return-value, unused-ignore]

    async def add(self, item: T) -> T:
        item.user_id = self.user_id  # type: ignore[attr-defined, unused-ignore]
        self.session.add(item)
        await self.session.flush()
        return item
