"""Точка входа: ``python -m habit_bot``."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import Mapping

from habit_bot import __version__
from habit_bot.kernel.config import ConfigError, Settings, load_settings
from habit_bot.kernel.errors.catalog import admin_message
from habit_bot.kernel.logs import setup_logging
from habit_bot.kernel.migrations import current_revision, head_revision
from habit_bot.modules import KNOWN_MODULES

log = logging.getLogger("habit_bot")

EXIT_CONFIG = 2
EXIT_MIGRATIONS = 3


def prepare(env: Mapping[str, str]) -> Settings | int:
    """Проверяет всё, что нужно до запуска. Возвращает настройки или код выхода."""
    try:
        settings = load_settings(env, KNOWN_MODULES)
    except ConfigError as err:
        # Полный список проблем — в лог контейнера и оттуда в отчёт «Выкладки» (раздел 7.4.3).
        print(err.report(), file=sys.stderr, flush=True)
        return EXIT_CONFIG
    setup_logging(settings.log_level, settings.data_dir / "logs")
    if settings.database_url.startswith("sqlite"):
        head, current = head_revision(), current_revision(settings.db_path)
        if current != head:
            text = admin_message("DB-MIGRATION", {"current": current or "пусто", "head": head})
            log.error(text, extra={"code": "DB-MIGRATION"})
            print(text, file=sys.stderr, flush=True)
            return EXIT_MIGRATIONS
    log.info("Запуск habit-bot %s", __version__)
    return settings


def run() -> None:  # pragma: no cover — запуск процесса проверяется пробным запуском контейнера в CI
    prepared = prepare(os.environ)
    if isinstance(prepared, int):
        sys.exit(prepared)
    from habit_bot.app import build_app

    asyncio.run(build_app(prepared).run())
