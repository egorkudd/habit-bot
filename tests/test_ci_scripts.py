"""Раздел 7.4.4: сводка CI показывает упавший тест и «ожидалось / получено»; пороги покрытия; таблица ошибок."""

from pathlib import Path
from typing import Any

import pytest

from scripts import ci_summary, coverage_gate, gen_error_table

JUNIT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="3" failures="1" errors="1">
  <testcase classname="tests.test_food" name="test_cocktail" file="tests/test_food.py" line="10">
    <properties><property name="description" value="Раздел 9: «Коктейль» добавляет 322 ккал и 140 ₽"/></properties>
    <failure message="AssertionError: ожидалось 322, получено 0">def test_cocktail():
&gt;       assert got == 322
E       AssertionError: ожидалось 322, получено 0

tests/test_food.py:14: AssertionError</failure>
  </testcase>
  <testcase classname="tests.test_x" name="test_error"><error>boom
RuntimeError: упало</error></testcase>
  <testcase classname="tests.test_ok" name="test_fine"/>
</testsuite></testsuites>"""


def test_summary_shows_failed_test(tmp_path: Path) -> None:
    """Сводка: имя теста, описание со ссылкой на критерий, «ожидалось / получено», файл и строка."""
    junit = tmp_path / "junit.xml"
    junit.write_text(JUNIT, encoding="utf-8")
    summary = tmp_path / "summary.md"
    assert ci_summary.main([str(junit), "--step", "2. Модульные тесты", "--summary", str(summary)]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "### 2. Модульные тесты: не прошли 2 из 3 ❌" in text
    assert "| `tests.test_food::test_cocktail` | Раздел 9: «Коктейль» добавляет 322 ккал и 140 ₽ |" in text
    assert "ожидалось 322, получено 0" in text
    assert "`tests/test_food.py:14`" in text
    assert "RuntimeError: упало" in text


def test_summary_all_green(tmp_path: Path, capsys: Any) -> None:
    """Все тесты прошли — короткая строка."""
    junit = tmp_path / "junit.xml"
    junit.write_text('<testsuite><testcase classname="a" name="b"/></testsuite>', encoding="utf-8")
    assert ci_summary.main([str(junit)]) == 0
    assert "все 1 тестов прошли" in capsys.readouterr().out


def test_summary_without_report(tmp_path: Path, capsys: Any) -> None:
    """Тесты не запустились — сводка говорит об этом прямо."""
    assert ci_summary.main([str(tmp_path / "нет.xml")]) == 1
    assert "тесты не запустились" in capsys.readouterr().out


def _coverage(domain: float, total: float) -> dict[str, Any]:
    return {
        "files": {
            "habit_bot/kernel/domain/config_rules.py": {
                "summary": {"percent_covered": domain}, "missing_lines": [10, 11, 12, 20], "missing_branches": [[3, 4]],
            },
            "habit_bot/app.py": {"summary": {"percent_covered": 80.0}, "missing_lines": [5]},
        },
        "totals": {"percent_covered": total},
    }


def test_coverage_gate_passes() -> None:
    """Бизнес-логика 100%, весь проект не ниже 90% — проверка зелёная."""
    ok, text = coverage_gate.evaluate(_coverage(100.0, 93.0))
    assert ok is True
    assert "Пороги пройдены" in text


def test_coverage_gate_fails_on_domain_and_total(tmp_path: Path) -> None:
    """Раздел 9: покрытие ниже порога — красная проверка с файлами и непокрытыми строками."""
    import json

    report = tmp_path / "coverage.json"
    report.write_text(json.dumps(_coverage(95.0, 85.0)), encoding="utf-8")
    summary = tmp_path / "summary.md"
    assert coverage_gate.main([str(report), "--summary", str(summary)]) == 1
    text = summary.read_text(encoding="utf-8")
    assert "`habit_bot/kernel/domain/config_rules.py` | бизнес-логика | 95.0% из 100%" in text
    assert "строки 10–12, 20" in text
    assert "весь проект 85.0% (порог 90%)" in text


def test_ranges() -> None:
    """Непокрытые строки сворачиваются в диапазоны."""
    assert coverage_gate._ranges([]) == ""
    assert coverage_gate._ranges([1, 2, 3, 7]) == "1–3, 7"


def test_error_table_update_and_check(tmp_path: Path, capsys: Any) -> None:
    """README обновляется из каталога; проверка находит устаревшую таблицу."""
    readme = tmp_path / "README.md"
    readme.write_text("# x\n<!-- errors:start -->\nстарое\n<!-- errors:end -->\nконец\n", encoding="utf-8")
    assert gen_error_table.main(["--check"], readme_path=readme) == 1
    assert gen_error_table.main([], readme_path=readme) == 0
    assert gen_error_table.main(["--check"], readme_path=readme) == 0
    text = readme.read_text(encoding="utf-8")
    assert "| `CFG-ADMIN` |" in text and text.endswith("конец\n")
    with pytest.raises(ValueError):
        gen_error_table.updated("без меток")
    with pytest.raises(ValueError):
        gen_error_table.updated("<!-- errors:start --> без конца")
