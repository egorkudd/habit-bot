"""Проверка здоровья (раздел 7.3): БД, миграции на версии кода, отметка «бот жив», getMe, диск, память."""

import json
import os
import time
from pathlib import Path
from typing import Any

from aiohttp.test_utils import TestServer

from habit_bot import health
from habit_bot.app import write_heartbeat
from scripts.fake_bot_api import create_app


def test_light_check_ok(migrated_env: dict[str, str], clock: Any) -> None:
    """Здоровый бот: база открывается, схема на версии кода, свежая отметка."""
    write_heartbeat(Path(migrated_env["DATA_DIR"]), clock.now())
    result = health.run_checks(migrated_env, full=False)
    assert result["ok"] is True
    assert set(result["checks"]) == {"database", "migrations", "heartbeat"}


def test_no_database(base_env: dict[str, str]) -> None:
    """Нет базы — проверка не пройдена, миграции пропущены."""
    result = health.run_checks(base_env, full=False)
    assert result["ok"] is False
    assert result["checks"]["database"]["ok"] is False
    assert result["checks"]["migrations"]["detail"] == "пропущено: нет базы"


def test_stale_or_missing_heartbeat(migrated_env: dict[str, str], clock: Any) -> None:
    """Бот завис или не запустился: отметки нет или она старше 90 секунд."""
    assert health.run_checks(migrated_env, full=False)["checks"]["heartbeat"]["detail"] == "бот ещё не отметился"
    data_dir = Path(migrated_env["DATA_DIR"])
    write_heartbeat(data_dir, clock.now())
    old = time.time() - 600
    os.utime(data_dir / "tmp" / "heartbeat", (old, old))
    assert health.run_checks(migrated_env, full=False)["ok"] is False


def test_migrations_mismatch(migrated_env: dict[str, str]) -> None:
    """Схема не на версии кода — код DB-MIGRATION."""
    import sqlite3

    con = sqlite3.connect(Path(migrated_env["DATA_DIR"]) / "bot.db")
    con.execute("UPDATE alembic_version SET version_num='0000_old'")
    con.commit()
    con.close()
    check = health.run_checks(migrated_env, full=False)["checks"]["migrations"]
    assert check["ok"] is False
    assert check["code"] == "DB-MIGRATION"


def test_broken_database_file(base_env: dict[str, str]) -> None:
    """Повреждённый файл базы — понятная ошибка."""
    data_dir = Path(base_env["DATA_DIR"])
    data_dir.mkdir(parents=True)
    (data_dir / "bot.db").write_bytes(b"not a database at all, just text" * 10)
    assert health.check_database(data_dir / "bot.db")["ok"] is False


def test_config_error(base_env: dict[str, str]) -> None:
    """С ошибками в настройках проверка сразу не пройдена и показывает список."""
    result = health.run_checks({**base_env, "BOT_TOKEN": ""}, full=True)
    assert result["ok"] is False
    assert "CFG-TOKEN" in result["checks"]["config"]["detail"]


async def test_full_check_with_fake_telegram(migrated_env: dict[str, str], clock: Any, no_network: None) -> None:
    """Полная проверка: getMe отвечает (поддельный Bot API на localhost — без реального Telegram)."""
    write_heartbeat(Path(migrated_env["DATA_DIR"]), clock.now())
    server = TestServer(create_app(poll_delay=0))
    await server.start_server()
    try:
        env = {**migrated_env, "BOT_API_BASE": f"http://127.0.0.1:{server.port}"}
        import asyncio

        result = await asyncio.to_thread(health.run_checks, env, full=True)
    finally:
        await server.close()
    assert result["checks"]["telegram"] == {
        "ok": True, "detail": "getMe отвечает: @habit_test_bot", "critical": True,
    }
    assert {"disk", "memory"} <= set(result["checks"])


def test_telegram_unreachable(migrated_env: dict[str, str], no_network: None) -> None:
    """Telegram не отвечает — код TG-NET."""
    env = {**migrated_env, "BOT_API_BASE": "http://127.0.0.1:9"}
    check = health.check_telegram(health.load_settings(env, health.KNOWN_MODULES))
    assert check["ok"] is False
    assert check["code"] == "TG-NET"


def test_disk_and_memory(tmp_path: Path) -> None:
    """Диск и память — предупреждения, а не причина перезапуска."""
    disk = health.check_disk(tmp_path / "missing")
    assert disk["critical"] is False and 0 <= disk["percent"] <= 100
    meminfo = tmp_path / "meminfo"
    meminfo.write_text("MemTotal: 1000000 kB\nMemAvailable: 51200 kB\n", encoding="utf-8")
    memory = health.check_memory(meminfo)
    assert memory["free_mb"] == 50
    assert memory["ok"] is False
    assert health.check_memory(tmp_path / "нет")["ok"] is True


def test_main_output(migrated_env: dict[str, str], clock: Any, capsys: Any) -> None:
    """Код выхода 0 — здоров; JSON для сценариев, текст для людей."""
    write_heartbeat(Path(migrated_env["DATA_DIR"]), clock.now())
    assert health.main(["--json"], env=migrated_env) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert health.main([], env={**migrated_env, "BOT_TOKEN": ""}) == 1
    assert capsys.readouterr().out.startswith("❌ не здоров")
    text = health.format_text({"ok": True, "checks": {
        "disk": {"ok": False, "detail": "диск занят на 85%", "critical": False}}})
    assert text == "✅ здоров\n⚠️ disk: диск занят на 85%"
