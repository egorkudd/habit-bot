"""Границы модулей из [tool.importlinter] в pyproject.toml — без пакета import-linter (раздел 7.3, шаг 1).

Проверяет контракты типа «forbidden»: модуль из source_modules не импортирует (прямо) запрещённые пакеты.
Используется в scripts/local_check.sh, когда GitHub Actions недоступны."""

from __future__ import annotations

import ast
import fnmatch
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def module_name(path: Path) -> str:
    parts = path.relative_to(ROOT).with_suffix("").parts
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
    return found


def matches(name: str, pattern: str) -> bool:
    return name == pattern or name.startswith(pattern + ".") or fnmatch.fnmatch(name, pattern) \
        or fnmatch.fnmatch(name, pattern + ".*")


def main() -> int:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    files = {module_name(p): p for p in (ROOT / "habit_bot").rglob("*.py")}
    problems = []
    for contract in config["tool"]["importlinter"]["contracts"]:
        for name, path in files.items():
            if not any(matches(name, s) for s in contract["source_modules"]):
                continue
            for imported in imports(path):
                bad = next((f for f in contract["forbidden_modules"] if matches(imported, f)), None)
                if bad:
                    problems.append(f"«{contract['name']}»: {name} импортирует {imported}")
    for line in problems:
        print(f"❌ {line}")
    print("✅ Границы модулей соблюдены" if not problems else f"Нарушений: {len(problems)}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
