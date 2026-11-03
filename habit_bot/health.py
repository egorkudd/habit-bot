"""Проверка здоровья (раздел 7.3).

``python -m habit_bot.health`` — быстрая проверка для Docker: БД, миграции, отметка «бот жив».
``python -m habit_bot.health --full --json`` — для «Выкладки» и «Бот жив?»: плюс getMe к Telegram,
место на диске и память. Код выхода 0 — здоров.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from habit_bot.kernel.config import ConfigError, Settings, load_settings
from habit_bot.kernel.migrations import current_revision, head_revision
from habit_bot.modules import KNOWN_MODULES

HEARTBEAT_MAX_AGE_SECONDS = 90
DISK_WARN_PERCENT = 80
MEMORY_WARN_MB = 80
TELEGRAM_TIMEOUT_SECONDS = 10


def _result(ok: bool, detail: str, *, critical: bool = True, **extra: Any) -> dict[str, Any]:
    return {"ok": ok, "detail": detail, "critical": critical, **extra}


def check_database(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return _result(False, f"файл базы {db_path} не найден")
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            con.execute("SELECT count(*) FROM sqlite_master").fetchone()
        finally:
            con.close()
    except sqlite3.Error as err:
        return _result(False, f"база не открывается: {err}")
    return _result(True, "база открывается")


def check_migrations(db_path: Path) -> dict[str, Any]:
    head, current = head_revision(), current_revision(db_path)
    if current != head:
        return _result(False, f"схема на ревизии {current or 'пусто'}, код ждёт {head}", code="DB-MIGRATION")
    return _result(True, f"схема на ревизии {head}")


def check_heartbeat(data_dir: Path, now: datetime) -> dict[str, Any]:
    path = data_dir / "tmp" / "heartbeat"
    if not path.exists():
        return _result(False, "бот ещё не отметился")
    age = now.timestamp() - path.stat().st_mtime
    if age > HEARTBEAT_MAX_AGE_SECONDS:
        return _result(False, f"последняя отметка {int(age)} с назад")
    return _result(True, f"отметка {int(age)} с назад")


def check_disk(data_dir: Path) -> dict[str, Any]:
    usage = shutil.disk_usage(data_dir if data_dir.exists() else data_dir.parent)
    percent = round(usage.used * 100 / usage.total)
    return _result(percent < DISK_WARN_PERCENT, f"диск занят на {percent}%", critical=False, percent=percent,
                   code="SYS-DISK")


def check_memory(meminfo: Path = Path("/proc/meminfo")) -> dict[str, Any]:
    try:
        lines = meminfo.read_text(encoding="utf-8").splitlines()
    except OSError:
        return _result(True, "нет данных о памяти", critical=False, free_mb=None)
    values = {line.split(":")[0]: line.split()[1] for line in lines if ":" in line and len(line.split()) > 1}
    free_mb = int(values.get("MemAvailable", "0")) // 1024
    return _result(free_mb >= MEMORY_WARN_MB, f"свободно {free_mb} МБ", critical=False, free_mb=free_mb,
                   code="SYS-MEM")


async def _get_me(settings: Settings) -> str:
    from aiogram import Bot

    from habit_bot.channels.telegram.channel import build_session

    bot = Bot(settings.bot_token, session=build_session(settings))
    try:
        me = await asyncio.wait_for(bot.get_me(), TELEGRAM_TIMEOUT_SECONDS)
    finally:
        await bot.session.close()
    return f"@{me.username}"


def check_telegram(settings: Settings) -> dict[str, Any]:
    try:
        username = asyncio.run(_get_me(settings))
    except Exception as err:
        return _result(False, f"getMe не отвечает: {type(err).__name__}", code="TG-NET")
    return _result(True, f"getMe отвечает: {username}")


def run_checks(env: Mapping[str, str], *, full: bool, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    try:
        settings = load_settings(env, KNOWN_MODULES)
    except ConfigError as err:
        return {"ok": False, "checks": {"config": _result(False, err.report())}}
    data_dir = settings.data_dir
    checks: dict[str, dict[str, Any]] = {"database": check_database(settings.db_path)}
    checks["migrations"] = (
        check_migrations(settings.db_path) if checks["database"]["ok"] else _result(False, "пропущено: нет базы")
    )
    checks["heartbeat"] = check_heartbeat(data_dir, now)
    if full:
        checks["telegram"] = check_telegram(settings)
        checks["disk"] = check_disk(data_dir)
        checks["memory"] = check_memory()
    ok = all(c["ok"] for c in checks.values() if c["critical"])
    return {"ok": ok, "checks": checks}


def format_text(result: dict[str, Any]) -> str:
    lines = [("✅ здоров" if result["ok"] else "❌ не здоров")]
    for name, check in result["checks"].items():
        mark = "✅" if check["ok"] else ("❌" if check["critical"] else "⚠️")
        lines.append(f"{mark} {name}: {check['detail']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Проверка здоровья habit-bot")
    parser.add_argument("--full", action="store_true", help="плюс Telegram, диск и память")
    parser.add_argument("--json", action="store_true", help="вывод в JSON")
    args = parser.parse_args(argv)
    result = run_checks(os.environ if env is None else env, full=args.full)
    print(json.dumps(result, ensure_ascii=False) if args.json else format_text(result))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
