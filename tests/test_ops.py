"""Служебные команды «Выкладки»: бэкап (одна последняя копия), восстановление, миграции, тексты оповещений."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from habit_bot import ops


def _data(env: dict[str, str]) -> Path:
    return Path(env["DATA_DIR"])


def test_backup_keeps_single_copy(migrated_env: dict[str, str]) -> None:
    """Раздел 9: после нескольких бэкапов на сервере лежит одна копия БД."""
    assert ops.main(["backup"], env=migrated_env) == 0
    assert ops.main(["backup"], env=migrated_env) == 0
    files = sorted(p.name for p in (_data(migrated_env) / "backup").iterdir())
    assert files == ["bot.db.bak"]


def test_failed_backup_keeps_previous(migrated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch,
                                      capsys: Any) -> None:
    """Раздел 9: если новый бэкап не удался, предыдущая копия остаётся на месте."""
    assert ops.main(["backup"], env=migrated_env) == 0
    target = _data(migrated_env) / "backup" / "bot.db.bak"
    before = target.read_bytes()
    real_connect = sqlite3.connect

    def failing(path: Any, *args: Any, **kwargs: Any) -> Any:
        if str(path).endswith(".tmp"):
            raise sqlite3.OperationalError("database or disk is full")
        return real_connect(path, *args, **kwargs)

    monkeypatch.setattr(ops.sqlite3, "connect", failing)
    assert ops.main(["backup"], env=migrated_env) == 1
    assert "💾 Бэкап не создан: database or disk is full." in capsys.readouterr().err
    assert target.read_bytes() == before
    assert sorted(p.name for p in target.parent.iterdir()) == ["bot.db.bak"]


def test_corrupted_copy_rejected(migrated_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Копия, не прошедшая проверку целостности, не заменяет старую и не остаётся на диске."""
    assert ops.main(["backup"], env=migrated_env) == 0
    target = _data(migrated_env) / "backup" / "bot.db.bak"
    before = target.read_bytes()
    monkeypatch.setattr(ops, "integrity_status", lambda path: "*** in database main ***")
    with pytest.raises(sqlite3.DatabaseError, match="копия повреждена"):
        ops.make_backup(_data(migrated_env) / "bot.db", target)
    assert target.read_bytes() == before
    assert sorted(p.name for p in target.parent.iterdir()) == ["bot.db.bak"]


def test_backup_without_database(base_env: dict[str, str], capsys: Any) -> None:
    """Первая выкладка: базы ещё нет — бэкап не нужен."""
    assert ops.main(["backup"], env=base_env) == 0
    assert "базы ещё нет" in capsys.readouterr().out


def test_restore(migrated_env: dict[str, str]) -> None:
    """Откат возвращает базу из последнего бэкапа."""
    assert ops.main(["backup"], env=migrated_env) == 0
    db = _data(migrated_env) / "bot.db"
    db.write_bytes(b"broken")
    (db.parent / "bot.db-wal").write_bytes(b"x")
    assert ops.main(["restore"], env=migrated_env) == 0
    assert not (db.parent / "bot.db-wal").exists()
    con = sqlite3.connect(db)
    assert con.execute("SELECT version_num FROM alembic_version").fetchone() == ("0008_workouts",)
    con.close()


def test_restore_without_backup(base_env: dict[str, str], capsys: Any) -> None:
    """Нет бэкапа — восстановление не удалось, понятное сообщение."""
    assert ops.main(["restore"], env=base_env) == 1
    assert "нет бэкапа" in capsys.readouterr().err


def test_render(capsys: Any) -> None:
    """Сценарии Actions берут тексты оповещений из того же каталога, что и бот."""
    assert ops.main(["render", "DEPLOY-FAIL", "version=0.2.0", "step=Миграции", "rollback=Вернул 0.1.0.",
                     "url=https://x"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("❌ Выкладка 0.2.0 не удалась на шаге «Миграции». Вернул 0.1.0.")
    assert ops.main(["render", "ACCESS-NO-INVITE", "--user"]) == 0
    assert capsys.readouterr().out.startswith("Бот доступен по приглашению")
    assert ops.main(["render", "NO-SUCH"]) == 2
    with pytest.raises(SystemExit):
        ops.main(["render", "TG-NET", "без-равно"])


def test_check_config(base_env: dict[str, str], capsys: Any) -> None:
    """«Выкладка» до остановки старой версии проверяет настройки новой."""
    assert ops.main(["check-config"], env=base_env) == 0
    assert ops.main(["check-config"], env={**base_env, "ADMIN_TG_IDS": ""}) == 2
    assert "1. CFG-ADMIN" in capsys.readouterr().out


def test_revisions(migrated_env: dict[str, str], capsys: Any) -> None:
    """Ревизии для отката: какую ждёт код и какая в базе."""
    assert ops.main(["migration-head"], env=migrated_env) == 0
    assert ops.main(["current-revision"], env=migrated_env) == 0
    assert capsys.readouterr().out.split() == ["0008_workouts", "0008_workouts"]
    assert ops.sync_url_from_env({"DATABASE_URL": "sqlite+aiosqlite:///x.db"}) == "sqlite:///x.db"
    assert ops.data_dir_from_env({}) == Path("/data")
