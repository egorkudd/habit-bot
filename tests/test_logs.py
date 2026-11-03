"""Логи (раздел 7): JSON без Telegram-ID, хранятся 14 дней и не больше 50 МБ."""

import json
import logging
from pathlib import Path

from habit_bot.kernel.logs import CappedRotatingHandler, JsonFormatter, current_handler, current_user_id, setup_logging


def _record(msg: str, **extra: object) -> logging.LogRecord:
    record = logging.LogRecord("habit_bot.test", logging.ERROR, __file__, 1, msg, None, None)
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_fields() -> None:
    """Строка лога: время, уровень, код ошибки, внутренний id пользователя, обработчик, сообщение."""
    token_user = current_user_id.set(7)
    token_handler = current_handler.set("food.add")
    try:
        line = json.loads(JsonFormatter().format(_record("Сбой", code="INTERNAL", incident="E-0001")))
    finally:
        current_user_id.reset(token_user)
        current_handler.reset(token_handler)
    assert {k: line[k] for k in ("level", "code", "user", "handler", "msg", "incident")} == {
        "level": "ERROR", "code": "INTERNAL", "user": 7, "handler": "food.add", "msg": "Сбой", "incident": "E-0001",
    }
    assert "ts" in line and "version" in line


def test_json_with_exception() -> None:
    """Трассировка ошибки попадает в лог."""
    try:
        raise ValueError("плохо")
    except ValueError:
        import sys

        record = _record("ошибка")
        record.exc_info = sys.exc_info()
    assert "ValueError: плохо" in json.loads(JsonFormatter().format(record))["exc"]


def test_rotation_by_size_and_total_limit(tmp_path: Path) -> None:
    """Файл ротируется по размеру, а общий объём логов не превышает лимит."""
    handler = CappedRotatingHandler(tmp_path / "bot.log", days=14, max_file_bytes=200, max_total_bytes=600)
    handler.setFormatter(logging.Formatter("%(message)s"))
    for n in range(60):
        handler.emit(_record(f"строка номер {n:03d} " + "x" * 40))
    handler.close()
    files = list(tmp_path.iterdir())
    total = sum(p.stat().st_size for p in files)
    assert len(files) > 1
    assert total <= 600 + 200


def test_old_archives_removed(tmp_path: Path) -> None:
    """Архивы старше 14 дней удаляются."""
    handler = CappedRotatingHandler(tmp_path / "bot.log", days=2)
    for day in range(1, 6):
        (tmp_path / f"bot.log.2026-10-0{day}_00-00-00").write_text("x", encoding="utf-8")
    handler.enforce_limits()
    handler.close()
    assert sorted(p.name for p in handler.archives()) == ["bot.log.2026-10-04_00-00-00", "bot.log.2026-10-05_00-00-00"]


def test_setup_logging(tmp_path: Path) -> None:
    """Логи пишутся в stdout и в файл с ротацией."""
    setup_logging("INFO", tmp_path / "logs")
    logging.getLogger("habit_bot.test").info("старт")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert "старт" in (tmp_path / "logs" / "bot.log").read_text(encoding="utf-8")
    setup_logging("INFO", None)
    assert len(logging.getLogger().handlers) == 1
