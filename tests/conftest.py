"""Общие фикстуры. Telegram и языковая модель в тестах — только поддельные, без сети (раздел 7.3)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ADMIN_ID = 111111111
OTHER_ID = 222222222
TOKEN = "123456789:" + "A" * 35  # поддельный токен собирается в коде, чтобы его не принял за секрет gitleaks


def pytest_assertrepr_compare(op: str, left: Any, right: Any) -> list[str] | None:
    """Падающие сравнения читаются как требования: «ожидалось X, получено Y» (раздел 7.4.4).

    Соглашение: слева фактическое значение, справа ожидаемое — ``assert got == expected``.
    """
    if op == "==":
        return [f"ожидалось {right!r}, получено {left!r}"]
    return None


INTEGRATION_FIXTURES = {"app", "settings", "migrated_env", "fake_session"}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Тесты с базой и поддельным Telegram — интеграционные (шаг «3. Интеграционные тесты»)."""
    for item in items:
        if INTEGRATION_FIXTURES.intersection(getattr(item, "fixturenames", ())):
            item.add_marker(pytest.mark.integration)


@pytest.fixture(autouse=True)
def _describe(request: pytest.FixtureRequest, record_property: Any) -> None:
    """Описание теста (docstring) попадает в отчёт JUnit и в сводку CI."""
    doc = getattr(request.function, "__doc__", None)
    if doc:
        record_property("description", " ".join(doc.split()))


class FixedClock:
    def __init__(self, now: datetime) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current

    def advance(self, **kwargs: float) -> None:
        self.current += timedelta(**kwargs)


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(datetime(2026, 11, 3, 12, 0, tzinfo=UTC))


@pytest.fixture
def base_env(tmp_path: Path) -> dict[str, str]:
    return {
        "BOT_TOKEN": TOKEN,
        "ADMIN_TG_IDS": str(ADMIN_ID),
        "BACKUP_PASSWORD": "очень-длинный-пароль",
        "DATA_DIR": str(tmp_path / "data"),
    }


@pytest.fixture
def migrated_env(base_env: dict[str, str]) -> dict[str, str]:
    from habit_bot import ops

    assert ops.main(["migrate"], env=base_env) == 0
    return base_env


@pytest.fixture
def settings(migrated_env: dict[str, str]) -> Any:
    from habit_bot.kernel.config import load_settings
    from habit_bot.modules import KNOWN_MODULES

    return load_settings(migrated_env, KNOWN_MODULES)


@pytest.fixture
def fake_session() -> Any:
    from tests.fakes import FakeTelegramSession

    return FakeTelegramSession()


@pytest.fixture
def geocoder() -> Any:
    from tests.fakes import FakeGeocoder

    return FakeGeocoder()


@pytest.fixture
async def app(settings: Any, fake_session: Any, clock: FixedClock, geocoder: Any) -> AsyncIterator[Any]:
    from habit_bot.app import build_app

    application = build_app(settings, telegram_session=fake_session, clock=clock, geocoder=geocoder)
    await application.startup()
    yield application
    await application.close()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Страховка: реальные сокеты наружу в тестах запрещены."""
    import socket

    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise RuntimeError(f"Тест пытается выйти в сеть: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", guarded)
    yield


OWNER_PROFILE = {
    "name": "Егор", "sex": "male", "birth_date": "2003-03-15", "height_cm": "178", "weight_kg": "75",
    "activity": "light", "mode": "gain", "experience": "intermediate",
}


async def register_active(app: Any, tg_id: int = ADMIN_ID, *, invite_code: str | None = None, **overrides: str) -> Any:
    """Пользователь, прошедший анкету (для тестов, которым анкета не важна). Возвращает Actor."""
    from datetime import date
    from decimal import Decimal

    from habit_bot.modules.users.domain.kbju import Activity, Experience, GoalMode, Sex
    from habit_bot.modules.users.dto import ProfileData

    values = {**OWNER_PROFILE, **overrides}
    actor = await app.ctx.services["users.sign_in"].execute(tg_id, values["name"], invite_code=invite_code)
    profiles = app.ctx.services["users.profiles"]
    data = ProfileData(
        name=values["name"], sex=Sex(values["sex"]), birth_date=date.fromisoformat(values["birth_date"]),
        height_cm=Decimal(values["height_cm"]), weight_kg=Decimal(values["weight_kg"]),
        activity=Activity(values["activity"]), mode=GoalMode(values["mode"]), target_weight=None,
        experience=Experience(values["experience"]),
    )
    await profiles.complete_onboarding(actor, data, targets=profiles.targets(data), source="calc")
    return actor
