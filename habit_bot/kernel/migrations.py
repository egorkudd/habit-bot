"""Миграции Alembic: применяются «Выкладкой» до запуска новой версии (раздел 7.3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def alembic_config(sync_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_url)
    return cfg


def head_revision() -> str:
    heads = ScriptDirectory.from_config(alembic_config("sqlite://")).get_heads()
    if len(heads) != 1:
        raise RuntimeError(f"Ожидалась одна голова миграций, найдено: {heads}")
    return str(heads[0])


def current_revision(db_path: Path) -> str | None:
    """Ревизия схемы из таблицы alembic_version; ``None`` — база пустая или её нет."""
    if not db_path.exists():
        return None
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = con.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        con.close()
    return row[0] if row else None


def migrate(sync_url: str, target: str = "head") -> None:
    """Поднимает или опускает схему до ``target``."""
    cfg = alembic_config(sync_url)
    script = ScriptDirectory.from_config(cfg)
    db_path = Path(sync_url.removeprefix("sqlite:///"))
    current = current_revision(db_path) if sync_url.startswith("sqlite:///") else None
    if target == "base":
        command.downgrade(cfg, "base")
        return
    if target == "head" or current is None:
        command.upgrade(cfg, target)
        return
    # Цель ниже текущей ревизии — опускаем (откат на старую версию), иначе поднимаем.
    ancestors = {rev.revision for rev in script.iterate_revisions(current, "base")}
    if target in ancestors:
        command.downgrade(cfg, target)
    else:
        command.upgrade(cfg, target)
