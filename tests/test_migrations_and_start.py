"""Раздел 7.3, шаг «5. Миграции», и проверки перед запуском бота."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from habit_bot import main as entry
from habit_bot.app import heartbeat_path, write_heartbeat
from habit_bot.kernel.migrations import current_revision, head_revision, migrate


def _tables(db: Path) -> set[str]:
    con = sqlite3.connect(db)
    try:
        return {row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        con.close()


def test_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    """Миграции поднимаются на пустой базе, опускаются и поднимаются снова."""
    db = tmp_path / "bot.db"
    url = f"sqlite:///{db}"
    assert current_revision(db) is None
    migrate(url)
    assert current_revision(db) == head_revision() == "0007_habits"
    assert {"users", "identities", "idempotency_keys", "admin_alerts", "dialog_states"} <= _tables(db)
    migrate(url, "base")
    assert "users" not in _tables(db)
    assert current_revision(db) is None
    migrate(url, "0001_initial")
    migrate(url, "0001_initial")
    assert current_revision(db) == "0001_initial"
    assert "dialog_states" not in _tables(db)
    migrate(url)
    assert current_revision(db) == "0007_habits"
    new_tables = {"users_profile", "users_goal", "users_invite", "users_body_weight", "source_cache", "days_status"}
    assert new_tables <= _tables(db)


def test_current_revision_without_alembic_table(tmp_path: Path) -> None:
    """База без таблицы версий считается пустой."""
    db = tmp_path / "empty.db"
    sqlite3.connect(db).close()
    assert current_revision(db) is None


def test_prepare_reports_config_problems(base_env: dict[str, str], capsys: Any) -> None:
    """Раздел 7.4.3: с ошибками в настройках бот не запускается и печатает полный список."""
    code = entry.prepare({**base_env, "ADMIN_TG_IDS": "", "BOT_TOKEN": ""})
    assert code == entry.EXIT_CONFIG
    err = capsys.readouterr().err
    assert "1. CFG-ADMIN" in err
    assert "2. CFG-TOKEN" in err


def test_prepare_requires_migrations(base_env: dict[str, str], capsys: Any) -> None:
    """Бот не стартует на базе, схема которой не на версии кода."""
    assert entry.prepare(base_env) == entry.EXIT_MIGRATIONS
    assert "код ждёт 0007_habits" in capsys.readouterr().err


def test_prepare_ok(migrated_env: dict[str, str]) -> None:
    """С правильными настройками и схемой подготовка проходит."""
    settings = entry.prepare(migrated_env)
    assert not isinstance(settings, int)
    assert (settings.data_dir / "logs" / "bot.log").exists()


def test_heartbeat_written(tmp_path: Path, clock: Any) -> None:
    """Отметка «бот жив» для проверки здоровья."""
    write_heartbeat(tmp_path, clock.now())
    assert heartbeat_path(tmp_path).read_text(encoding="utf-8") == clock.now().isoformat()


def test_migrate_upgrade_to_newer_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Цель выше текущей ревизии — миграции поднимаются."""
    db = tmp_path / "bot.db"
    migrate(f"sqlite:///{db}", "0001_initial")
    calls: list[str] = []
    monkeypatch.setattr("habit_bot.kernel.migrations.command.upgrade", lambda cfg, target: calls.append(target))
    migrate(f"sqlite:///{db}", "0009_future")
    assert calls == ["0009_future"]
