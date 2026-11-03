"""Пороги покрытия (раздел 7.3, шаг «4. Покрытие»).

Бизнес-логика (файлы в каталогах ``domain/``) — 100% строк и ветвлений, весь проект — не ниже 90%.
Порог для изменённого кода (95%) проверяет diff-cover отдельно.
Пишет понятную сводку: какие файлы и строки не покрыты.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DOMAIN_THRESHOLD = 100.0
TOTAL_THRESHOLD = 90.0


def _ranges(lines: list[int]) -> str:
    if not lines:
        return ""
    parts: list[str] = []
    start = prev = lines[0]
    for line in lines[1:]:
        if line == prev + 1:
            prev = line
            continue
        parts.append(str(start) if start == prev else f"{start}–{prev}")
        start = prev = line
    parts.append(str(start) if start == prev else f"{start}–{prev}")
    return ", ".join(parts)


def evaluate(report: dict[str, Any]) -> tuple[bool, str]:
    """Возвращает (пройдено ли, markdown-сводка)."""
    problems: list[str] = []
    for path, data in sorted(report["files"].items()):
        if "/domain/" not in f"/{path}":
            continue
        percent = float(data["summary"]["percent_covered"])
        if percent < DOMAIN_THRESHOLD:
            missing = _ranges(sorted(data.get("missing_lines", [])))
            branches = len(data.get("missing_branches", []))
            problems.append(
                f"| `{path}` | бизнес-логика | {percent:.1f}% из {DOMAIN_THRESHOLD:.0f}% | "
                f"строки {missing or '—'}; непокрытых ветвлений: {branches} |"
            )
    total = float(report["totals"]["percent_covered"])
    if total < TOTAL_THRESHOLD:
        worst = sorted(report["files"].items(), key=lambda kv: kv[1]["summary"]["percent_covered"])[:5]
        for path, data in worst:
            problems.append(
                f"| `{path}` | весь проект | {data['summary']['percent_covered']:.1f}% | "
                f"строки {_ranges(sorted(data.get('missing_lines', []))) or '—'} |"
            )
    lines = [f"### 4. Покрытие: весь проект {total:.1f}% (порог {TOTAL_THRESHOLD:.0f}%)"]
    if problems:
        lines += ["", "| Файл | Порог | Покрытие | Что не покрыто |", "|---|---|---|---|", *problems]
    else:
        lines.append("Пороги пройдены: бизнес-логика 100%, весь проект не ниже 90%.")
    return not problems, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--summary", type=Path, help="куда дописать сводку (GITHUB_STEP_SUMMARY)")
    args = parser.parse_args(argv)
    ok, text = evaluate(json.loads(args.coverage_json.read_text(encoding="utf-8")))
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
