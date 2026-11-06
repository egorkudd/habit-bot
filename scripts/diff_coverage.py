"""Покрытие нового и изменённого кода против ветки (замена diff-cover, раздел 7.3, шаг 4): не ниже 95%.

    python scripts/diff_coverage.py coverage.json origin/main"""

from __future__ import annotations

import json
import re
import subprocess
import sys

THRESHOLD = 95.0


def changed_lines(base: str) -> dict[str, set[int]]:
    diff = subprocess.run(["git", "diff", "-U0", base, "--", "habit_bot", "scripts"], capture_output=True, text=True,
                          check=True).stdout
    result: dict[str, set[int]] = {}
    current = None
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") and line.endswith(".py") else None
        elif current and line.startswith("@@"):
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            assert m is not None
            start, count = int(m[1]), int(m[2] or 1)
            result.setdefault(current, set()).update(range(start, start + count))
    return result


def main() -> int:
    with open(sys.argv[1], encoding="utf-8") as file:
        data = json.load(file)["files"]
    total = covered = 0
    report = []
    for path, lines in sorted(changed_lines(sys.argv[2] if len(sys.argv) > 2 else "origin/main").items()):
        info = data.get(path)
        if info is None or "migrations/" in path:
            continue
        measured = lines & (set(info["executed_lines"]) | set(info["missing_lines"]))
        missing = sorted(lines & set(info["missing_lines"]))
        total += len(measured)
        covered += len(measured) - len(missing)
        if missing:
            report.append(f"{path}: не покрыты строки {', '.join(map(str, missing))}")
    percent = 100.0 if not total else 100 * covered / total
    for line in report:
        print(line)
    print(f"Покрытие нового и изменённого кода: {percent:.1f}% (порог {THRESHOLD:.0f}%)")
    return 0 if percent >= THRESHOLD else 1


if __name__ == "__main__":
    sys.exit(main())
