"""Каталог поведенческих сценариев (docs/test-scenarios.md) из описаний тестов tests/scenarios.

Описание теста начинается с номера: «S-07. Владелец впервые пишет боту: …». Запуск без аргументов
перезаписывает файл; ``--check`` — только сверяет (тест в CI падает, если каталог устарел).
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCENARIOS = ROOT / "tests" / "scenarios"
DOC = ROOT / "docs" / "test-scenarios.md"
CASE = re.compile(r"^(S-\d+)\.\s*(.+)$", re.S)

HEADER = """# Поведенческие сценарии

Тесты, где «живой» пользователь пишет боту, нажимает кнопки, ошибается, отвлекается и возвращается —
в поддельном Telegram, с поддельными часами и перезапусками бота (`tests/scenarios`, отметка `scenario`).
Запуск: `pytest -m scenario`. Каталог собирается из описаний тестов: `python scripts/gen_scenarios_doc.py`.

| № | Сценарий | Тест |
|---|---|---|
"""


def collect(folder: Path = SCENARIOS) -> list[tuple[str, str, str]]:
    cases: list[tuple[str, str, str]] = []
    for path in sorted(folder.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name.startswith("test_"):
                doc = " ".join((ast.get_docstring(node) or "").split())
                match = CASE.match(doc)
                if match:
                    cases.append((match[1], match[2].replace("|", "\\|"), f"`{path.name}::{node.name}`"))
    return sorted(cases, key=lambda c: int(c[0][2:]))


def render(cases: list[tuple[str, str, str]]) -> str:
    return HEADER + "".join(f"| {n} | {text} | {test} |\n" for n, text, test in cases)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(collect())
    if args.check:
        current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
        if current != text:
            print("docs/test-scenarios.md устарел: запустите python scripts/gen_scenarios_doc.py", file=sys.stderr)
            return 1
        return 0
    DOC.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
