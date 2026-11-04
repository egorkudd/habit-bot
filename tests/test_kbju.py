"""Раздел 4.1 и критерии раздела 9 «Регистрация и профиль»: расчёт КБЖУ, ограничения, ручные значения, анкета."""

from datetime import date
from decimal import Decimal

import pytest

from habit_bot.kernel.errors import AppError
from habit_bot.modules.users.domain.kbju import (
    Activity,
    BodyInputs,
    GoalMode,
    Sex,
    age_on,
    allowed_modes,
    basal_metabolism,
    bmi,
    calculate_targets,
    check_manual_targets,
    check_target_weight,
)
from habit_bot.modules.users.domain.profile import parse_birth_date, parse_kbju_line, parse_name

TODAY = date(2026, 11, 4)


def test_owner_example() -> None:
    """Раздел 9: «Мужчина, 23 года, 178 см, 75 кг, лёгкая активность, набор» → 2800 / 160 / 80 / 360."""
    inputs = BodyInputs(Sex.MALE, date(2003, 3, 15), Decimal(178), Decimal(75), Activity.LIGHT, GoalMode.GAIN)
    targets = calculate_targets(inputs, TODAY)
    assert targets.as_tuple() == (2800, 160, 80, 360)
    assert targets.bmr == Decimal("1752.50")
    assert targets.tdee == Decimal("2409.69")
    assert targets.warnings == ()


def test_woman_example() -> None:
    """Раздел 9: «Женщина, 30 лет, 165 см, 60 кг, средняя активность, поддержание» → 2050 / 110 / 55 / 280."""
    inputs = BodyInputs(Sex.FEMALE, date(1996, 1, 10), Decimal(165), Decimal(60), Activity.MEDIUM, GoalMode.MAINTAIN)
    assert calculate_targets(inputs, TODAY).as_tuple() == (2050, 110, 55, 280)


def test_loss_floor_and_low_carbs() -> None:
    """Снижение: не ниже базового обмена и 1200 ккал (женщины); сработало ограничение — предупреждение."""
    inputs = BodyInputs(Sex.FEMALE, date(1960, 1, 1), Decimal(150), Decimal(50), Activity.MINIMAL, GoalMode.LOSS)
    targets = calculate_targets(inputs, TODAY)
    assert targets.kcal == 1200
    assert targets.kcal % 50 == 0
    assert any("не ниже" in w for w in targets.warnings)


def test_loss_without_floor() -> None:
    """Обычное снижение: расход − 500 ккал без предупреждения об ограничении."""
    inputs = BodyInputs(Sex.MALE, date(1990, 1, 1), Decimal(180), Decimal(95), Activity.MEDIUM, GoalMode.LOSS)
    targets = calculate_targets(inputs, TODAY)
    expected = basal_metabolism(Sex.MALE, Decimal(95), Decimal(180), 36) * Decimal("1.55") - 500
    assert abs(targets.kcal - expected) <= 25
    assert not any("не ниже" in w for w in targets.warnings)


def test_loss_floor_is_bmr_for_men() -> None:
    """У мужчин нижняя граница — базовый обмен, если он выше 1500; результат округляется вверх до 50."""
    inputs = BodyInputs(Sex.MALE, date(2000, 1, 1), Decimal(200), Decimal(120), Activity.MINIMAL, GoalMode.LOSS)
    targets = calculate_targets(inputs, TODAY)
    bmr = basal_metabolism(Sex.MALE, Decimal(120), Decimal(200), 26)
    assert targets.kcal >= bmr
    assert targets.kcal % 50 == 0


def test_low_carbs_warning() -> None:
    """Углеводов меньше 100 г — предупреждение; отрицательных углеводов не бывает."""
    inputs = BodyInputs(Sex.FEMALE, date(1950, 1, 1), Decimal(140), Decimal(110), Activity.MINIMAL, GoalMode.LOSS)
    targets = calculate_targets(inputs, TODAY)
    assert targets.carbs >= 0
    assert any("Углеводов меньше 100" in w for w in targets.warnings)


def test_age_and_bmi() -> None:
    """Возраст — полных лет на дату; ИМТ с одним знаком."""
    assert age_on(date(2003, 3, 15), date(2026, 3, 14)) == 22
    assert age_on(date(2003, 3, 15), date(2026, 3, 15)) == 23
    assert bmi(Decimal(75), Decimal(178)) == Decimal("23.7")


def test_loss_unavailable_for_low_bmi() -> None:
    """Раздел 3.0, шаг 7: снижение недоступно при ИМТ < 18,5."""
    assert GoalMode.LOSS not in allowed_modes(Decimal(50), Decimal(178))
    assert allowed_modes(Decimal(75), Decimal(178)) == [GoalMode.GAIN, GoalMode.MAINTAIN, GoalMode.LOSS]


def test_manual_targets() -> None:
    """Ручные КБЖУ: 1200–6000 ккал; расхождение Б·4 + Ж·9 + У·4 с ккал больше 5% — предупреждение."""
    assert check_manual_targets(Decimal(2800), Decimal(160), Decimal(80), Decimal(360)) == []
    warnings = check_manual_targets(Decimal(2000), Decimal(160), Decimal(80), Decimal(360))
    assert warnings == ["По Б·4 + Ж·9 + У·4 выходит 2 800 ккал, а указано 2 000 — разница больше 5%."]
    with pytest.raises(AppError) as err:
        check_manual_targets(Decimal(900), Decimal(50), Decimal(30), Decimal(100))
    assert err.value.user_text() == "Калории — от 1200 до 6000 ккал. Вы ввели 900"


def test_target_weight_matches_goal() -> None:
    """Целевой вес согласован с целью: набор — больше текущего, снижение — меньше, поддержание — ±5%."""
    check_target_weight(GoalMode.GAIN, Decimal(75), Decimal(80))
    check_target_weight(GoalMode.LOSS, Decimal(75), Decimal(70))
    check_target_weight(GoalMode.MAINTAIN, Decimal(75), Decimal(76))
    with pytest.raises(AppError) as err:
        check_target_weight(GoalMode.GAIN, Decimal(75), Decimal(70))
    assert err.value.user_text() == "Целевой вес при наборе — от 75,5 до 250 кг. Вы ввели 70"
    with pytest.raises(AppError):
        check_target_weight(GoalMode.LOSS, Decimal(75), Decimal(80))
    with pytest.raises(AppError) as err:
        check_target_weight(GoalMode.MAINTAIN, Decimal(75), Decimal(90))
    assert "от 71,2 до 78,8 кг" in err.value.user_text()


def test_name() -> None:
    """Имя 1–32 символа, лишние пробелы убираются."""
    assert parse_name("  Егор   К ") == "Егор К"
    with pytest.raises(AppError) as err:
        parse_name("  ")
    assert err.value.user_text() == "Имя — от 1 до 32 символов. Сейчас 0"
    with pytest.raises(AppError):
        parse_name("я" * 33)


def test_birth_date() -> None:
    """Раздел 9: дата рождения в будущем — ошибка ввода; год полностью, не раньше 1900."""
    assert parse_birth_date("15.03.2003", TODAY) == date(2003, 3, 15)
    with pytest.raises(AppError) as err:
        parse_birth_date("15.03.2027", TODAY)
    assert err.value.code == "INPUT-FUTURE"
    with pytest.raises(AppError) as err:
        parse_birth_date("15.03", TODAY)
    assert err.value.code == "INPUT-DATE"
    with pytest.raises(AppError) as err:
        parse_birth_date("15.03.1899", TODAY)
    assert err.value.user_text() == "Дата рождения — от 01.01.1900 до 04.11.2026. Вы ввели 15.03.1899"


def test_kbju_line() -> None:
    """Ручные КБЖУ одной строкой: пробелы или «/», точка и запятая."""
    assert parse_kbju_line("2800 160 80 360") == (Decimal(2800), Decimal(160), Decimal(80), Decimal(360))
    assert parse_kbju_line("421/52,4/15.6/17,8") == (Decimal(421), Decimal("52.4"), Decimal("15.6"), Decimal("17.8"))
    with pytest.raises(AppError) as err:
        parse_kbju_line("2800 160 80")
    assert err.value.user_text() == (
        "Напишите 4 числа через пробел: ккал, белки, жиры, углеводы. Пример: 2800 160 80 360")
    with pytest.raises(AppError) as err:
        parse_kbju_line("2800 160 80 мало")
    assert err.value.code == "INPUT-NUMBER"
