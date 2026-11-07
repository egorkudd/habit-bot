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
    assert current_revision(db) == head_revision() == "0015_stats_nutrients"
    assert {"users", "identities", "idempotency_keys", "admin_alerts", "dialog_states"} <= _tables(db)
    migrate(url, "base")
    assert "users" not in _tables(db)
    assert current_revision(db) is None
    migrate(url, "0001_initial")
    migrate(url, "0001_initial")
    assert current_revision(db) == "0001_initial"
    assert "dialog_states" not in _tables(db)
    migrate(url)
    assert current_revision(db) == "0015_stats_nutrients"
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
    assert "код ждёт 0015_stats_nutrients" in capsys.readouterr().err


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


def test_food_catalog_v2_replaces_base_products(tmp_path: Path) -> None:
    """Правки 1.0.2, миграция 0014: старые продукты каталога и их копии у пользователей удалены, записи еды остались
    (без ссылки, значения — копии); новые продукты скопированы тем, у кого были базовые; гречка и банан остались
    со своей ценой; свой рецепт и продукт админа не тронуты; повторный подъём ничего не дублирует."""
    db = tmp_path / "bot.db"
    url = f"sqlite:///{db}"
    migrate(url, "0013_chat_messages")
    con = sqlite3.connect(db)
    now = "2026-11-01 10:00:00"

    def item(user: int | None, key: str | None, name: str, source: int | None = None,
             price: float | None = None) -> int:
        cur = con.execute(
            "INSERT INTO food_item (user_id, catalog_key, name, kind, composition, unit, kcal, protein, fat, carbs, "
            "price, active, source_catalog_id, public_id, created_at, updated_at, version) "
            "VALUES (?, ?, ?, 'product', '', 'piece', 100, 1, 1, 1, ?, 1, ?, ?, ?, ?, 1)",
            (user, key, name, price, source, f"{abs(hash((user, name))):032x}"[:32], now, now))
        return int(cur.lastrowid or 0)

    for uid in (1, 2):
        con.execute("INSERT INTO users (id, name, role, status, last_active_at, public_id, created_at, updated_at, "
                    "version) VALUES (?, 'Аня', 'user', 'active', ?, ?, ?, ?, 1)", (uid, now, f"{uid:032x}", now, now))
    thigh, banana = item(None, "chicken_thigh", "Куриное бедро"), item(None, "banana", "Банан")
    admin_made = item(None, None, "Хлебец")
    copy = item(1, None, "Куриное бедро", thigh)
    item(1, None, "Банан", banana, price=20)
    own = item(2, None, "Коктейль")
    con.execute("INSERT INTO food_entry (user_id, day, logged_at, food_item_id, name, quantity, unit, kcal, "
                "protein, fat, carbs, source, public_id, created_at, updated_at) VALUES (1, '2026-11-01', ?, ?, "
                "'Куриное бедро', 2, 'piece', 500, 46, 34, 0, 'button', ?, ?, ?)", (now, copy, "e" * 32, now, now))
    con.commit()
    con.close()
    migrate(url)
    migrate(url, "0013_chat_messages")
    migrate(url)
    con = sqlite3.connect(db)
    names = {(u, n, p) for u, n, p in con.execute("SELECT user_id, name, price FROM food_item")}
    entry_row = con.execute("SELECT name, kcal, food_item_id FROM food_entry").fetchone()
    con.close()
    assert (None, "Куриное бедро", None) not in names and (1, "Куриное бедро", None) not in names
    assert {(1, "Банан", 20.0), (2, "Коктейль", None), (None, "Хлебец", None)} <= names
    assert {n for u, n, _ in names if u == 1} == {"Банан", "Куриное филе", "Творог 5%", "Рис сухой (пакет 80 г)",
                                                    "Картофель"}
    assert {n for u, n, _ in names if u == 2} == {"Коктейль"}
    assert entry_row == ("Куриное бедро", 500.0, None)
    assert admin_made and own
