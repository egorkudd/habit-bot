"""Раздел 3.3, 4.5 и критерии раздела 9 «Еда и зарядка»: значения, шаги, номер в дне, личная цель и темп."""

from datetime import date

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.warmup.domain.warmup import (
    DEFAULT_SET,
    DEFAULT_STEP,
    Measure,
    apply_step,
    format_minus_step,
    format_step,
    format_value,
    goal_progress,
    next_number,
    ordinal,
    parse_step,
    parse_value,
    parse_values_line,
    progress_line,
    values_example,
)


def test_plank_plus_15_seconds() -> None:
    """Раздел 9: «Планка +15 сек» — 5:45 → 6:00; «Отжимания +5» дважды — 50 → 60."""
    assert format_value(Measure.SECONDS, apply_step(345, DEFAULT_STEP[Measure.SECONDS])) == "6:00"
    assert apply_step(apply_step(50, 5), 5) == 60
    assert apply_step(3, 5, -1) == 0


def test_default_set_and_steps() -> None:
    """Набор по умолчанию: отжимания, мостик, планка (время), спина; шаги +5 и +15 сек."""
    assert [e.short for e in DEFAULT_SET] == ["Отжимания", "Мостик", "Планка", "Спина"]
    assert [e.measure for e in DEFAULT_SET].count(Measure.SECONDS) == 1
    assert format_step(Measure.REPS, 10) == "+10"
    assert format_step(Measure.SECONDS, 15) == "+15 сек"
    assert format_step(Measure.SECONDS, 60) == "+1:00"


def test_values_and_steps_parsing() -> None:
    """Время — «5:45», «5.45» или секунды; повторы — целым числом; шаг больше нуля."""
    assert parse_value(Measure.SECONDS, "6:15") == 375
    assert parse_value(Measure.SECONDS, "345") == 345
    assert parse_value(Measure.REPS, "60") == 60
    for measure, text, code in ((Measure.SECONDS, "6:75", "INPUT-TIME"), (Measure.SECONDS, "5:00:00", "INPUT-TIME"),
                                (Measure.REPS, "12,5", "INPUT-NUMBER"), (Measure.REPS, "сто", "INPUT-NUMBER"),
                                (Measure.REPS, "20000", "INPUT-RANGE")):
        with pytest.raises(AppError) as err:
            parse_value(measure, text)
        assert err.value.code == code
    assert parse_step(Measure.REPS, "10") == 10
    with pytest.raises(AppError) as err:
        parse_step(Measure.REPS, "0")
    assert err.value.code == "INPUT-RANGE"


def test_number_in_day() -> None:
    """Раздел 9: вторая зарядка за день получает номер 2."""
    assert next_number([]) == 1
    assert next_number([1]) == 2
    assert ordinal(2) == "2-я"


def test_goal_progress_pace() -> None:
    """Раздел 4.5: нужный темп = (цель − лучший) / дни до даты; фактический — за 14 дней."""
    progress = goal_progress(target=660, target_date=date(2026, 12, 3), start_value=345, set_on=date(2026, 10, 22),
                             today=date(2026, 11, 3), best=360, best_before_window=340)
    assert (progress.left, progress.days_left) == (300, 30)
    assert str(progress.needed_per_day) == "10.0"
    assert str(progress.actual_per_day) == "1.4"
    assert not progress.achieved
    line = progress_line("Планка", Measure.SECONDS, progress, date(2026, 12, 3))
    assert line.startswith("🎯 Планка: лучший 6:00 · цель 11:00 к 03.12 · осталось 5:00 · нужно +10 сек/день · "
                           "за 14 дней +1,4 сек/день")
    assert progress.behind and "⚠️ отставание: по плану сейчас" in line


def test_goal_achieved_and_on_track() -> None:
    """Цель достигнута — отдельная строка; без отставания — без предупреждения; дни до даты не меньше 1."""
    done = goal_progress(target=60, target_date=date(2026, 11, 3), start_value=50, set_on=date(2026, 11, 1),
                         today=date(2026, 11, 5), best=62, best_before_window=70)
    assert done.achieved and done.days_left == 1 and done.left == 0
    assert progress_line("Отжимания", Measure.REPS, done, date(2026, 11, 3)) == (
        "🎯 Отжимания: цель 60 достигнута — лучший 62")
    on_track = goal_progress(target=100, target_date=date(2026, 12, 1), start_value=50, set_on=date(2026, 11, 1),
                             today=date(2026, 11, 2), best=55, best_before_window=60)
    line = progress_line("Отжимания", Measure.REPS, on_track, date(2026, 12, 1))
    assert "⚠️" not in line and "за 14 дней −0,4/день" in line


def test_values_line_and_minus_step() -> None:
    exercises = [("Отжимания", Measure.REPS), ("Планка", Measure.SECONDS)]
    assert parse_values_line(exercises, " 55   6:15 ") == [55, 375]
    assert values_example([Measure.REPS, Measure.SECONDS]) == "20 1:00"
    assert values_example([Measure.REPS, Measure.SECONDS], [0, 0]) == "20 1:00"
    assert values_example([Measure.REPS, Measure.SECONDS], [50, 345]) == "50 5:45"
    assert format_minus_step(Measure.SECONDS, 15) == "−15 сек"
    assert format_minus_step(Measure.REPS, 5) == "−5"
    for text, problem in (("55", "Не хватает: Планка"), ("55 6:15 7", "Лишнее значение: 7")):
        with pytest.raises(AppError) as err:
            parse_values_line(exercises, text)
        assert err.value.user_text() == f"{problem}. Нужно значений: 2, по порядку набора. Например: 20 1:00"
