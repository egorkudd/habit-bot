"""Раздел 3.4.1, 3.5, 4.9 и критерии раздела 9 «Тренировки и бег»: база упражнений, фильтры, подходы,
тоннаж, темп."""

from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.runs.domain.runs import (
    DistanceGroup,
    RunValue,
    comparison,
    group_of,
    km,
    pace,
    parse_distance,
    parse_run_time,
    records,
    run_line,
    speed,
    suspicious,
)
from habit_bot.modules.workouts.catalog import BY_KEY, EXERCISES
from habit_bot.modules.workouts.domain.training import (
    Band,
    Equipment,
    ExerciseSpec,
    Filters,
    Group,
    Kind,
    Measure,
    Place,
    SetValue,
    Suggest,
    duration_label,
    format_sets,
    offered,
    parse_counts,
    parse_weight,
    step_weight,
    tonnage,
    week_start,
)

GYM_GROUPS = {Group.LEGS: 15, Group.HINGE: 6, Group.CHEST: 10, Group.BACK: 10, Group.SHOULDERS: 7, Group.ARMS: 10,
              Group.CORE: 6}
OUTDOOR_GROUPS = {Group.BAR: 10, Group.DIPS: 5, Group.BENCH: 8, Group.STANDING: 8}


def test_catalog_size_and_groups() -> None:
    """Раздел 3.4.1 и 6.1: не меньше 70 для зала, 35 для площадки и 15 с резинкой; минимум по группам."""
    assert len(EXERCISES) >= 120 and len(BY_KEY) == len(EXERCISES)  # ключи без повторов
    band = [e for e in EXERCISES if e.equipment is Equipment.BAND]
    gym = [e for e in EXERCISES if e.place is not Place.OUTDOOR and e.equipment is not Equipment.BAND]
    outdoor = [e for e in EXERCISES if e.place is Place.OUTDOOR and e.equipment is not Equipment.BAND]
    assert (len(gym) >= 70, len(outdoor) >= 35, len(band) >= 15) == (True, True, True)
    groups = Counter(e.group for e in EXERCISES)
    for group, minimum in {**GYM_GROUPS, **OUTDOOR_GROUPS, Group.BAND: 15}.items():
        assert groups[group] >= minimum, group
    assert len({e.name for e in EXERCISES}) == len(EXERCISES)


def test_catalog_fields_are_consistent() -> None:
    """Каждое упражнение заполнено по 3.4.1: ссылки «проще / сложнее» ведут в базу, шаг веса и «вес каждой» —
    только у «вес × повторы», диапазон повторов осмысленный, «лёжа на земле» не предлагается на улице."""
    for e in EXERCISES:
        for link in (e.easier, e.harder):
            assert link is None or (link in BY_KEY and link != e.key), e.key
        assert (e.weight_step is not None) == (e.measure is Measure.WEIGHT_REPS), e.key
        assert not e.per_dumbbell or e.equipment is Equipment.DUMBBELL, e.key
        assert 1 <= e.reps_low <= e.reps_high <= 120, e.key
        assert not (e.floor and e.place is Place.OUTDOOR), e.key
        assert e.measure is not Measure.BAND_REPS or e.equipment is Equipment.BAND, e.key
        assert e.loaded is False or e.place is Place.OUTDOOR, e.key
    women_only = {e.key for e in EXERCISES if e.suggest is Suggest.WOMEN}
    men_only = {e.key for e in EXERCISES if e.suggest is Suggest.MEN}
    assert {"bb_shrug", "db_shrug", "upright_row"} <= men_only  # пример раздела 3.4.1: женщинам не предлагаются
    assert {"hip_abduction", "hip_adduction", "cable_kickback"} <= women_only


def test_offered_filters() -> None:
    plank, pullup, band_row = BY_KEY["plank"], BY_KEY["pullup_wide"], BY_KEY["band_row"]
    gym, outdoor = Filters(Kind.GYM, sex="m"), Filters(Kind.OUTDOOR, sex="m")
    assert offered(plank, gym) and not offered(plank, outdoor)          # лёжа на земле — не на улице
    assert offered(pullup, outdoor) and not offered(pullup, gym)        # площадка — не в зале
    assert not offered(BY_KEY["weighted_pullup"], outdoor)              # отягощение на улице — задел
    assert offered(band_row, outdoor) and not offered(band_row, Filters(Kind.OUTDOOR, band=False))
    assert not offered(pullup, Filters(Kind.OUTDOOR, missing=frozenset({Equipment.PULLUP_BAR})))
    assert not offered(BY_KEY["hip_abduction"], gym)
    assert offered(BY_KEY["hip_abduction"], Filters(Kind.GYM, sex="f"))
    assert offered(BY_KEY["hip_abduction"], Filters(Kind.GYM, sex="m", show_all=True))
    assert offered(pullup, Filters(Kind.FREE)) and offered(BY_KEY["bench_press"], Filters(Kind.FREE))


def test_sets_parsing_and_tonnage() -> None:
    """Раздел 9: 110 × 8 × 4 = 3520; «вес каждой» — ×2."""
    assert parse_counts("4×8") == parse_counts("4x8") == parse_counts("4 * 8") == [8, 8, 8, 8]
    assert parse_counts("8 8 7 6") == parse_counts("8, 8, 7, 6") == [8, 8, 7, 6]
    assert parse_counts("3×45", seconds=True) == [45, 45, 45]
    assert parse_counts("1:00 0:50", seconds=True) == [60, 50]
    for bad in ("4×", "13×8", "4×0", "4×201", "", "много", "1 2 3 4 5 6 7 8 9 10 11 12 13"):
        with pytest.raises(AppError) as err:
            parse_counts(bad)
        assert err.value.code == "INPUT-SETS"
    with pytest.raises(AppError):
        parse_counts("2×2:00:00", seconds=True)
    assert parse_weight("112,5 кг") == Decimal("112.5") == parse_weight(" 112.5 ")
    sets = [SetValue(reps=8, weight=Decimal(110))] * 4
    assert tonnage(sets) == 3520 and tonnage(sets, per_dumbbell=True) == 7040
    assert tonnage([SetValue(reps=10), SetValue(seconds=30)]) == 0
    assert step_weight(Decimal(110), Decimal("2.5"), -1) == Decimal("107.5")
    assert step_weight(Decimal(1), Decimal("2.5"), -1) == 0


def test_format_sets() -> None:
    w = Decimal(110)
    assert format_sets(Measure.WEIGHT_REPS, [SetValue(reps=8, weight=w)] * 4) == "110 кг 4×8"
    assert format_sets(Measure.WEIGHT_REPS, [SetValue(reps=10, weight=Decimal(20))] * 3, True) == "2×20 кг 3×10"
    assert format_sets(Measure.WEIGHT_REPS, [SetValue(reps=8, weight=w), SetValue(reps=6, weight=Decimal(115))]) == (
        "110×8, 115×6 кг")
    assert format_sets(Measure.REPS, [SetValue(reps=8), SetValue(reps=7)]) == "8, 7"
    assert format_sets(Measure.TIME, [SetValue(seconds=45)] * 3) == "3×0:45"
    assert format_sets(Measure.BAND_REPS, [SetValue(reps=15, band=Band.MEDIUM)] * 3) == "средняя 3×15"
    assert format_sets(Measure.BAND_REPS, [SetValue(reps=15, band=Band.MEDIUM), SetValue(reps=12)]) == (
        "резинка 15, 12")
    assert format_sets(Measure.REPS, []) == "нет подходов"
    assert week_start(date(2026, 11, 8)) == date(2026, 11, 2) == week_start(date(2026, 11, 2))
    assert duration_label(70) == "70 мин"
    assert ExerciseSpec.__dataclass_fields__["floor"].default is False


def test_run_math() -> None:
    """Раздел 9: 5,2 км за 28:40 → темп 5:31 мин/км, 10,88 км/ч; «28.40» = «28:40»; «28» — минуты."""
    distance, seconds = Decimal("5.2"), parse_run_time("28.40")
    assert seconds == parse_run_time("28:40") == 1720 and parse_run_time("28") == 1680
    assert parse_run_time("1:05:10") == 3910
    assert (pace(distance, seconds), speed(distance, seconds)) == (331, Decimal("10.88"))
    assert run_line(RunValue(distance, seconds)) == "🏃 5,2 км · 28:40 · темп 5:31 · 10,88 км/ч"
    assert parse_distance("5,2 км") == distance and km(Decimal(5)) == "5,0 км"
    with pytest.raises(AppError):
        parse_distance("400")
    assert suspicious(149) and suspicious(901) and not suspicious(150) and not suspicious(900)
    assert [group_of(Decimal(d)) for d in ("4.9", "5", "9.9", "10")] == [
        DistanceGroup.SHORT, DistanceGroup.MIDDLE, DistanceGroup.MIDDLE, DistanceGroup.LONG]


def test_run_comparison_and_records() -> None:
    first, faster = RunValue(Decimal("5.2"), 1720), RunValue(Decimal(5), 1620)
    assert comparison(first, None) == "первый забег в группе «5–10 км»"
    assert comparison(faster, first) == "▲ на 0:07 быстрее прошлого"
    assert comparison(first, faster) == "▼ на 0:07 медленнее прошлого"
    assert comparison(first, first) == "= темп как в прошлый раз"
    assert records(first, []) == []
    assert records(faster, [first]) == ["🏆 Лучший темп 5–10 км: 5:24"]
    long = RunValue(Decimal(12), 3910)
    assert records(long, [first, faster]) == ["🏆 Самая длинная дистанция: 12,0 км"]
