"""Раздел README «Что делать при ошибке» собирается из каталога ошибок (раздел 7.4).

``python scripts/gen_error_table.py`` — обновить README, ``--check`` — только проверить.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from habit_bot.kernel.errors.catalog import markdown_table  # noqa: E402

START = "<!-- errors:start -->"
END = "<!-- errors:end -->"


def updated(readme: str) -> str:
    head, sep, rest = readme.partition(START)
    if not sep:
        raise ValueError(f"В README нет метки {START}")
    _, sep2, tail = rest.partition(END)
    if not sep2:
        raise ValueError(f"В README нет метки {END}")
    return f"{head}{START}\n{markdown_table()}\n{END}{tail}"


def main(argv: list[str] | None = None, readme_path: Path = ROOT / "README.md") -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    current = readme_path.read_text(encoding="utf-8")
    fresh = updated(current)
    if args.check:
        if fresh != current:
            print("Таблица ошибок в README устарела: запустите python scripts/gen_error_table.py")
            return 1
        print("Таблица ошибок в README совпадает с каталогом")
        return 0
    readme_path.write_text(fresh, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
