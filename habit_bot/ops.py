"""Служебные команды для сценариев GitHub Actions: ``python -m habit_bot.ops <команда>``.

``render`` работает без зависимостей проекта: его вызывают прямо на сервере GitHub,
чтобы тексты оповещений брались из того же каталога ошибок, что и в боте.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from collections.abc import Mapping
from pathlib import Path

from habit_bot.kernel.errors.catalog import CATALOG, admin_message, user_message

BACKUP_NAME = "bot.db.bak"


def data_dir_from_env(env: Mapping[str, str]) -> Path:
    return Path(env.get("DATA_DIR") or "/data")


def db_path_from_env(env: Mapping[str, str]) -> Path:
    return data_dir_from_env(env) / "bot.db"


def sync_url_from_env(env: Mapping[str, str]) -> str:
    url = env.get("DATABASE_URL") or f"sqlite:///{db_path_from_env(env)}"
    return url.replace("+aiosqlite", "")


def backup_path(data_dir: Path) -> Path:
    return data_dir / "backup" / BACKUP_NAME


def integrity_status(path: Path) -> str:
    con = sqlite3.connect(path)
    try:
        return str(con.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        con.close()


def make_backup(db_path: Path, target: Path) -> str:
    """Копия базы через SQLite backup API.

    Новая копия пишется во временный файл и заменяет старую только после проверки целостности,
    поэтому на сервере всегда есть одна рабочая копия (раздел 7, «Бэкапы»).
    """
    if not db_path.exists():
        return "базы ещё нет — бэкап не нужен"
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    tmp.unlink(missing_ok=True)
    try:
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(tmp)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        status = integrity_status(tmp)
        if status != "ok":
            raise sqlite3.DatabaseError(f"копия повреждена: {status}")
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return f"бэкап сохранён: {target} ({target.stat().st_size // 1024} КБ)"


def restore_backup(source: Path, db_path: Path) -> str:
    if not source.exists():
        raise FileNotFoundError(f"нет бэкапа {source}")
    tmp = db_path.with_name(db_path.name + ".restore")
    shutil.copyfile(source, tmp)
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    os.replace(tmp, db_path)
    return f"база восстановлена из {source}"


def parse_params(items: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep:
            raise SystemExit(f"Параметр «{item}» нужно записать как ключ=значение")
        params[key] = value
    return params


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(prog="python -m habit_bot.ops")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check-config", help="проверить настройки и вывести полный список проблем")
    migrate_p = sub.add_parser("migrate", help="применить миграции")
    migrate_p.add_argument("--to", default="head", help="ревизия (по умолчанию head)")
    sub.add_parser("migration-head", help="ревизия, которую ждёт код")
    sub.add_parser("current-revision", help="ревизия схемы в базе")
    sub.add_parser("backup", help="сделать бэкап базы (хранится одна последняя копия)")
    sub.add_parser("restore", help="восстановить базу из последнего бэкапа")
    render_p = sub.add_parser("render", help="текст оповещения из каталога ошибок")
    render_p.add_argument("code")
    render_p.add_argument("params", nargs="*", help="ключ=значение")
    render_p.add_argument("--user", action="store_true", help="текст для пользователя")
    args = parser.parse_args(argv)

    if args.command == "render":
        if args.code not in CATALOG:
            print(f"Неизвестный код {args.code}", file=sys.stderr)
            return 2
        params = parse_params(args.params)
        print(user_message(args.code, params) if args.user else admin_message(args.code, params))
        return 0

    if args.command == "check-config":
        from habit_bot.kernel.config import ConfigError, load_settings
        from habit_bot.modules import KNOWN_MODULES

        try:
            load_settings(env, KNOWN_MODULES)
        except ConfigError as err:
            print(err.report())
            return 2
        print("Настройки в порядке")
        return 0

    if args.command in {"migrate", "migration-head", "current-revision"}:
        from habit_bot.kernel.migrations import current_revision, head_revision, migrate

        if args.command == "migration-head":
            print(head_revision())
        elif args.command == "current-revision":
            print(current_revision(db_path_from_env(env)) or "")
        else:
            data_dir_from_env(env).mkdir(parents=True, exist_ok=True)
            migrate(sync_url_from_env(env), args.to)
            print(f"Схема на ревизии {current_revision(db_path_from_env(env))}")
        return 0

    data_dir = data_dir_from_env(env)
    if args.command == "backup":
        try:
            print(make_backup(db_path_from_env(env), backup_path(data_dir)))
        except (OSError, sqlite3.Error) as err:
            print(admin_message("BKP-FAIL", {"detail": str(err)}), file=sys.stderr)
            return 1
        return 0

    # restore
    try:
        print(restore_backup(backup_path(data_dir), db_path_from_env(env)))
    except OSError as err:
        print(f"Восстановление не удалось: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
