"""Структурированные логи (раздел 7): JSON, без содержимого записей и без Telegram-ID.

Хранятся 14 дней и не больше 50 МБ (раздел 7, «Место на диске»).
"""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import sys
from datetime import UTC, datetime
from pathlib import Path

from habit_bot import __version__

LOG_DAYS = 14
LOG_MAX_TOTAL_BYTES = 50 * 1024 * 1024
LOG_MAX_FILE_BYTES = 10 * 1024 * 1024

current_user_id: contextvars.ContextVar[int | None] = contextvars.ContextVar("current_user_id", default=None)
current_handler: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_handler", default=None)


class JsonFormatter(logging.Formatter):
    """Одна строка JSON на событие: время, уровень, код, внутренний id пользователя, обработчик, сообщение."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
            "level": record.levelname,
            "code": getattr(record, "code", None),
            "user": getattr(record, "user", None) or current_user_id.get(),
            "handler": getattr(record, "handler", None) or current_handler.get(),
            "msg": record.getMessage(),
            "logger": record.name,
            "version": __version__,
        }
        incident = getattr(record, "incident", None)
        if incident:
            payload["incident"] = incident
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps({k: v for k, v in payload.items() if v is not None}, ensure_ascii=False)


class CappedRotatingHandler(logging.handlers.TimedRotatingFileHandler):
    """Ротация раз в сутки и при превышении размера файла; общий объём ограничен ``max_total_bytes``."""

    def __init__(
        self, path: Path, *, days: int = LOG_DAYS, max_file_bytes: int = LOG_MAX_FILE_BYTES,
        max_total_bytes: int = LOG_MAX_TOTAL_BYTES,
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(path, when="midnight", backupCount=days, encoding="utf-8", utc=True)
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self._path = path

    def shouldRollover(self, record: logging.LogRecord) -> int:
        if self.stream is not None and self.stream.tell() >= self.max_file_bytes:
            return 1
        return super().shouldRollover(record)

    def doRollover(self) -> None:
        if self.stream is not None:
            self.stream.close()
            self.stream = None  # type: ignore[assignment, unused-ignore]
        # Имя архива с секундами, чтобы ротация по размеру несколько раз в день не затирала файлы.
        stamp = datetime.now(UTC).strftime("%Y-%m-%d_%H-%M-%S")
        target = self._path.with_name(f"{self._path.name}.{stamp}")
        n = 1
        while target.exists():
            target = self._path.with_name(f"{self._path.name}.{stamp}-{n}")
            n += 1
        if self._path.exists():
            self._path.rename(target)
        self.enforce_limits()
        self.stream = self._open()
        self.rolloverAt = self.computeRollover(int(datetime.now(UTC).timestamp()))

    def archives(self) -> list[Path]:
        return sorted(p for p in self._path.parent.glob(f"{self._path.name}.*") if p.is_file())

    def enforce_limits(self) -> None:
        """Удаляет самые старые архивы: сверх 14 дней и пока общий объём больше лимита."""
        archives = self.archives()
        while len(archives) > self.backupCount:
            archives.pop(0).unlink(missing_ok=True)
        current = self._path.stat().st_size if self._path.exists() else 0
        total = current + sum(p.stat().st_size for p in archives)
        while archives and total > self.max_total_bytes:
            oldest = archives.pop(0)
            total -= oldest.stat().st_size
            oldest.unlink(missing_ok=True)


def setup_logging(level: str, log_dir: Path | None) -> None:
    """Логи в stdout (для docker logs) и в файл с ротацией в ``log_dir``."""
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    formatter = JsonFormatter()
    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    root.addHandler(stdout)
    if log_dir is not None:
        file_handler = CappedRotatingHandler(log_dir / "bot.log")
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
