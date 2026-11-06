"""Локальная «Проверка» без GitHub Actions (06.11.2026): границы модулей, покрытие нового кода, поиск секретов."""

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from scripts import check_boundaries, diff_coverage, find_secrets

PYPROJECT = """
[[tool.importlinter.contracts]]
name = "Домен не знает о Telegram"
type = "forbidden"
source_modules = ["habit_bot.*.domain"]
forbidden_modules = ["aiogram"]
"""


def _tree(root: Path, files: dict[str, str]) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def test_boundaries_ok_and_violation(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """Домен без aiogram — зелёно; прямой импорт aiogram из домена — нарушение с именем модуля."""
    _tree(tmp_path, {"habit_bot/__init__.py": "", "habit_bot/food/domain/__init__.py": "import json\n",
                     "habit_bot/food/domain/calc.py": "from . import x\nfrom decimal import Decimal\n",
                     "habit_bot/food/ui.py": "import aiogram\n"})
    monkeypatch.setattr(check_boundaries, "ROOT", tmp_path)
    assert check_boundaries.main() == 0
    assert "✅ Границы модулей соблюдены" in capsys.readouterr().out
    (tmp_path / "habit_bot/food/domain/bad.py").write_text("from aiogram.types import Message\n", encoding="utf-8")
    assert check_boundaries.main() == 1
    out = capsys.readouterr().out
    assert "❌ «Домен не знает о Telegram»: habit_bot.food.domain.bad импортирует aiogram.types" in out
    assert "Нарушений: 1" in out


def test_boundaries_real_project_is_clean() -> None:
    """Настоящий проект соблюдает контракты из pyproject.toml."""
    assert check_boundaries.main() == 0


def test_boundaries_matches() -> None:
    assert check_boundaries.matches("aiogram.types", "aiogram")
    assert check_boundaries.matches("habit_bot.food.domain", "habit_bot.*.domain")
    assert not check_boundaries.matches("aiogramx", "aiogram")


DIFF = """diff --git a/scripts/x.py b/scripts/x.py
+++ b/scripts/x.py
@@ -1,0 +2,3 @@
@@ -9 +12 @@
+++ /dev/null
@@ -1 +0,0 @@
+++ b/README.md
@@ -1 +1 @@
+++ b/habit_bot/migrations/versions/0001.py
@@ -0,0 +1,2 @@
"""


def _coverage(tmp_path: Path, missing: list[int]) -> Path:
    data = {"files": {"scripts/x.py": {"executed_lines": [2, 3, 4, 12], "missing_lines": missing},
                      "habit_bot/migrations/versions/0001.py": {"executed_lines": [], "missing_lines": [1, 2]}}}
    path = tmp_path / "coverage.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_diff_coverage(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """Учитываются только добавленные строки .py (миграции — нет); ниже 95% — красный итог со строками."""
    calls = []

    def fake_run(args: list[str], **_: Any) -> Any:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=DIFF)

    monkeypatch.setattr(diff_coverage.subprocess, "run", fake_run)
    assert diff_coverage.changed_lines("main") == {"scripts/x.py": {2, 3, 4, 12},
                                                   "habit_bot/migrations/versions/0001.py": {1, 2}}
    monkeypatch.setattr("sys.argv", ["diff_coverage.py", str(_coverage(tmp_path, []))])
    assert diff_coverage.main() == 0
    assert calls[-1][3] == "origin/main"
    assert "Покрытие нового и изменённого кода: 100.0% (порог 95%)" in capsys.readouterr().out
    path = _coverage(tmp_path, [12])
    monkeypatch.setattr("sys.argv", ["diff_coverage.py", str(path), "base"])
    assert diff_coverage.main() == 1
    out = capsys.readouterr().out
    assert "scripts/x.py: не покрыты строки 12" in out and "75.0%" in out
    assert calls[-1][3] == "base"


def test_diff_coverage_nothing_changed(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    monkeypatch.setattr(diff_coverage.subprocess, "run",
                        lambda args, **_: subprocess.CompletedProcess(args, 0, stdout=""))
    monkeypatch.setattr("sys.argv", ["diff_coverage.py", str(_coverage(tmp_path, []))])
    assert diff_coverage.main() == 0
    assert "100.0%" in capsys.readouterr().out


@pytest.mark.parametrize(("text", "kind"), [
    ("BOT_TOKEN=1234567890:AAH" + "x" * 33, "токен Telegram-бота"),
    ("key = 'sk-" + "a" * 24 + "'", "ключ API (sk-…)"),
    ("ghp_" + "b" * 36, "токен GitHub"),
    ("-----BEGIN OPENSSH " + "PRIVATE KEY-----", "приватный ключ"),
])
def test_find_secrets_detects(tmp_path: Path, monkeypatch: Any, capsys: Any, text: str, kind: str) -> None:
    """Токен бота, ключ API, токен GitHub, приватный ключ — красный итог с файлом и видом секрета."""
    (tmp_path / "leak.txt").write_text(text, encoding="utf-8")
    (tmp_path / "image.bin").write_bytes(b"\xff\xfe\x00")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(find_secrets.subprocess, "run", lambda args, **_: subprocess.CompletedProcess(
        args, 0, stdout="leak.txt\nimage.bin\nmissing.txt\n"))
    assert find_secrets.main() == 1
    out = capsys.readouterr().out
    assert f"❌ leak.txt: {kind}" in out and "Найдено: 1" in out


def test_find_secrets_allows_test_fakes(tmp_path: Path, monkeypatch: Any, capsys: Any) -> None:
    """Поддельный токен тестов (AAAA…) секретом не считается."""
    (tmp_path / "conftest.py").write_text("TOKEN = '123456789:" + "A" * 35 + "'", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(find_secrets.subprocess, "run",
                        lambda args, **_: subprocess.CompletedProcess(args, 0, stdout="conftest.py\n"))
    assert find_secrets.main() == 0
    assert "✅ Секретов не найдено" in capsys.readouterr().out
