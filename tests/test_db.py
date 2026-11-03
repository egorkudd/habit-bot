"""Ядро базы: время в UTC, изоляция по user_id (раздел 4.4), версии объектов, события после commit."""

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.orm.exc import StaleDataError

from habit_bot.kernel.db import (
    SoftDeleteMixin,
    UnitOfWork,
    UserScopedRepository,
    UtcDateTime,
    make_engine,
    make_sessionmaker,
)
from habit_bot.kernel.events import DomainEvent, EventBus
from habit_bot.kernel.identity import Role, User


class _TestBase(DeclarativeBase):
    pass


class Note(SoftDeleteMixin, _TestBase):
    __tablename__ = "notes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(String(50))


class NoteRepository(UserScopedRepository[Note]):
    model = Note


class Saved(DomainEvent):
    pass


@pytest.fixture
async def notes_session(tmp_path: Any) -> Any:
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'notes.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(_TestBase.metadata.create_all)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as session:
        yield session
    await engine.dispose()


async def test_repository_isolated_by_user(notes_session: AsyncSession) -> None:
    """Раздел 9 «Изоляция»: пользователь B не видит записей A; удалённые записи не видны."""
    repo_a, repo_b = NoteRepository(notes_session, 1), NoteRepository(notes_session, 2)
    note = await repo_a.add(Note(text="А"))
    hidden = await repo_a.add(Note(text="удалена"))
    hidden.deleted_at = datetime.now(UTC)
    await notes_session.flush()
    assert await repo_b.get(note.id) is None
    assert (await repo_a.get(note.id)) is note
    assert [n.text for n in await repo_a.find()] == ["А"]
    assert await repo_b.find() == []
    assert await repo_a.find(Note.text == "нет") == []


@pytest.mark.parametrize("bad", [0, -1, True, "1"])
def test_repository_requires_user(bad: Any) -> None:
    """Запрос к пользовательским данным без user_id не построить."""
    with pytest.raises(ValueError):
        NoteRepository(None, bad)  # type: ignore[arg-type]


def test_utc_datetime_rejects_naive_time() -> None:
    """В базу пишется только время с часовым поясом, читается — в UTC."""
    column = UtcDateTime()
    with pytest.raises(ValueError):
        column.process_bind_param(datetime(2026, 1, 1), None)
    assert column.process_bind_param(None, None) is None
    assert column.process_result_value(None, None) is None
    aware = column.process_result_value(datetime(2026, 1, 1, 12), None)
    assert aware is not None and aware.tzinfo is UTC


async def test_stale_version_not_overwritten(app: Any) -> None:
    """Правка с двух мест: вторая правка устаревшей версии не перезаписывает первую молча."""
    async with app.ctx.uow() as uow:
        user = User(name="Аня", role=Role.USER, last_active_at=datetime.now(UTC))
        uow.session.add(user)
    sessionmaker = make_sessionmaker(app.engine)
    async with sessionmaker() as first, sessionmaker() as second:
        a = (await first.execute(select(User))).scalar_one()
        b = (await second.execute(select(User))).scalar_one()
        a.name = "Аня 2"
        await first.commit()
        b.name = "Аня 3"
        with pytest.raises(StaleDataError):
            await second.commit()


async def test_events_only_after_commit(app: Any) -> None:
    """Подписчики узнают об изменении только после commit; при откате событий нет; сбой подписчика не мешает."""
    events = EventBus()
    seen: list[str] = []

    async def broken(event: DomainEvent) -> None:
        raise RuntimeError("подписчик сломан")

    async def record(event: DomainEvent) -> None:
        seen.append(type(event).__name__)

    events.subscribe(Saved, broken)
    events.subscribe(Saved, record)
    sessionmaker = make_sessionmaker(app.engine)
    now = datetime.now(UTC)

    async with UnitOfWork(sessionmaker, events) as uow:
        uow.collect(Saved(user_id=1, occurred_at=now))
    assert seen == ["Saved"]

    with pytest.raises(RuntimeError):
        async with UnitOfWork(sessionmaker, events) as uow:
            uow.collect(Saved(user_id=1, occurred_at=now))
            raise RuntimeError("ошибка в сценарии")
    assert seen == ["Saved"]

