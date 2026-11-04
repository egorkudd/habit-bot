"""Каталог поведенческих сценариев совпадает с тестами; у каждого сценария уникальный номер."""

from collections import Counter

from scripts.gen_scenarios_doc import collect, main


def test_catalog_is_up_to_date() -> None:
    """docs/test-scenarios.md собран из описаний тестов tests/scenarios."""
    assert main(["--check"]) == 0


def test_numbers_are_unique() -> None:
    """Номера S-xx не повторяются, сценариев не меньше 26."""
    numbers = [n for n, _, _ in collect()]
    assert [n for n, c in Counter(numbers).items() if c > 1] == []
    assert len(numbers) >= 26


def test_outdated_catalog_detected(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Если каталог устарел, проверка падает с подсказкой."""
    import scripts.gen_scenarios_doc as gen

    monkeypatch.setattr(gen, "DOC", tmp_path / "doc.md")
    assert main(["--check"]) == 1
    assert main([]) == 0
    assert main(["--check"]) == 0
