"""Сводка запуска CI (раздел 7.4.4): какие тесты не прошли — описание, «ожидалось / получено», файл и строка."""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

_LOCATION = re.compile(r"(tests/[\w/.-]+\.py):(\d+)")


@dataclass(frozen=True)
class Failure:
    test: str
    description: str
    message: str
    location: str


def _clean(text: str) -> str:
    return " ".join(text.split()).replace("|", "\\|")


def parse_junit(path: Path) -> tuple[int, list[Failure]]:
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    failures: list[Failure] = []
    for case in cases:
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        props = {p.get("name"): p.get("value", "") for p in case.iter("property")}
        body = (problem.text or "") + " " + (problem.get("message") or "")
        matches = list(_LOCATION.finditer(body))
        match = matches[-1] if matches else None
        location = f"{match.group(1)}:{match.group(2)}" if match else case.get("file", "—")
        text_lines = [line for line in (problem.text or "").splitlines() if line.strip()]
        message = problem.get("message") or (text_lines[-1] if text_lines else "—")
        failures.append(Failure(
            test=f"{case.get('classname', '')}::{case.get('name', '')}",
            description=_clean(props.get("description") or "—"),
            message=_clean(str(message))[:300],
            location=location,
        ))
    return len(cases), failures


def render(step: str, total: int, failures: list[Failure]) -> str:
    if not failures:
        return f"### {step}: все {total} тестов прошли ✅"
    lines = [
        f"### {step}: не прошли {len(failures)} из {total} ❌",
        "",
        "| Тест | Что проверяет | Ожидалось / получено | Файл и строка |",
        "|---|---|---|---|",
    ]
    lines += [f"| `{f.test}` | {f.description} | {f.message} | `{f.location}` |" for f in failures]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("junit", type=Path)
    parser.add_argument("--step", default="Тесты")
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args(argv)
    if not args.junit.exists():
        text = f"### {args.step}: тесты не запустились — отчёт не создан, смотрите лог шага"
        failures: list[Failure] = [Failure("—", "—", "нет отчёта", "—")]
    else:
        total, failures = parse_junit(args.junit)
        text = render(args.step, total, failures)
    print(text)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(text + "\n\n")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
