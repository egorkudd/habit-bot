"""Раздел 7.4: у каждого кода есть текст и подсказка, каждый код используется, README совпадает с каталогом."""

import re
from pathlib import Path

import pytest

from habit_bot.kernel.errors import AppError, new_incident_id
from habit_bot.kernel.errors.catalog import CATALOG, Level, admin_message, report_line, user_message
from scripts.gen_error_table import updated

ROOT = Path(__file__).resolve().parent.parent
SEARCH_DIRS = ("habit_bot", "scripts", "deploy", ".github")
CATALOG_FILE = ROOT / "habit_bot" / "kernel" / "errors" / "catalog.py"


def _sources() -> str:
    chunks = []
    for folder in SEARCH_DIRS:
        for path in (ROOT / folder).rglob("*"):
            if path.is_file() and path != CATALOG_FILE and path.suffix in {".py", ".sh", ".yml", ".yaml"}:
                chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def test_every_code_has_texts() -> None:
    """У каждого кода заполнены описание, текст для администратора и подсказка; у пользовательских — текст."""
    for code, spec in CATALOG.items():
        assert spec.summary and spec.admin_text and spec.hint, code
        if spec.level is Level.USER:
            assert spec.user_text, code


def test_every_code_is_used() -> None:
    """Каждый код из каталога где-то используется в коде или сценариях."""
    sources = _sources()
    unused = [code for code in CATALOG if not re.search(rf"(?<![A-Z-]){re.escape(code)}(?![A-Z-])", sources)]
    assert unused == []


def test_readme_table_matches_catalog() -> None:
    """Раздел 9: таблица «Что делать при ошибке» в README совпадает с каталогом."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert updated(readme) == readme


def test_messages_fill_params_and_mark_missing() -> None:
    """Неизвестный параметр шаблона показывается как «?», а не роняет оповещение."""
    text = admin_message("DEPLOY-FAIL", {"version": "0.1.0", "step": "Миграции"})
    assert text.startswith("❌ Выкладка 0.1.0 не удалась на шаге «Миграции». ?")
    assert "Что сделать: подробности: ?" in text
    assert user_message("DB-MIGRATION") == ""
    assert report_line("CFG-TOKEN", {"detail": "BOT_TOKEN не задан"}).startswith("CFG-TOKEN: BOT_TOKEN не задан — ")


def test_app_error() -> None:
    """AppError несёт код из каталога и даёт текст для пользователя; неизвестный код — ошибка программиста."""
    err = AppError("INTERNAL", incident="E-1A2B")
    assert err.code == "INTERNAL"
    assert "E-1A2B" in err.user_text()
    with pytest.raises(KeyError):
        AppError("NO-SUCH-CODE")


def test_incident_id_format() -> None:
    """Код инцидента для пользователя и администратора: «E-» и 4 шестнадцатеричных символа."""
    incident = new_incident_id()
    assert incident.startswith("E-")
    assert len(incident) == 6
    int(incident[2:], 16)
