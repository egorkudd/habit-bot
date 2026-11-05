"""Состав выгрузки (раздел 3.12): файлы, колонки и их описания для README.csv. Имени и Telegram-ID нет нигде."""

from __future__ import annotations

from habit_bot.modules.export.domain.csv_format import Column as C
from habit_bot.modules.export.domain.csv_format import TableSpec

DAILY = TableSpec("daily", "daily_summary.csv", "Итоги по дням", "один день", (
    C("date", "день (логический: с 04:00 до 04:00)", "YYYY-MM-DD"),
    C("day_status", "normal — обычный, day_off — выходной"),
    C("kcal", "калории за день", "ккал"), C("protein", "белки", "г"), C("fat", "жиры", "г"),
    C("carbs", "углеводы", "г"), C("kcal_goal", "цель по калориям, действовавшая в этот день", "ккал"),
    C("protein_goal", "цель по белкам", "г"), C("fat_goal", "цель по жирам", "г"),
    C("carbs_goal", "цель по углеводам", "г"), C("kcal_left", "сколько калорий осталось до цели", "ккал"),
    C("cost_rub", "расход на еду (блюда без цены не учтены)", "₽"),
    C("warmups_done", "сколько зарядок сделано"), C("warmups_goal", "цель зарядок в день"),
    C("workouts", "тренировок за день (без бега)"), C("run_km", "пробежано", "км"),
    C("body_weight", "вес тела, если взвешивались", "кг"),
))
FOOD = TableSpec("food", "food.csv", "Еда", "одна запись еды", (
    C("date", "день", "YYYY-MM-DD"), C("time", "время записи", "HH:MM"), C("name", "блюдо или продукт"),
    C("quantity", "количество в единицах unit"), C("unit", "portion — порция, 100g — 100 граммов, piece — штука"),
    C("kcal", "калории записи", "ккал"), C("protein", "белки", "г"), C("fat", "жиры", "г"),
    C("carbs", "углеводы", "г"), C("cost_rub", "цена записи, пусто — без цены", "₽"),
    C("source", "как записано: button — кнопкой, other — «Другое», text — текстом"),
))
WARMUPS = TableSpec("warmups", "warmups.csv", "Зарядка", "одно упражнение в зарядке", (
    C("date", "день", "YYYY-MM-DD"), C("session_no", "номер зарядки в этот день"), C("exercise", "упражнение"),
    C("value", "результат: повторы или секунды"), C("unit", "reps — повторы, sec — секунды"),
))
WORKOUTS = TableSpec("workouts", "workouts.csv", "Тренировки", "один подход", (
    C("date", "день", "YYYY-MM-DD"), C("workout_type", "gym — зал, outdoor — площадка, free — свободная"),
    C("exercise", "упражнение"), C("set_no", "номер подхода в упражнении"),
    C("weight_kg", "вес (для гантелей — одной гантели)", "кг"), C("band", "резинка, если была"),
    C("reps", "повторы"), C("seconds", "время подхода", "сек"), C("feeling", "самочувствие (появится в v2)"),
    C("duration_min", "длительность всей тренировки", "мин"),
))
RUNS = TableSpec("runs", "runs.csv", "Бег", "один забег", (
    C("date", "день", "YYYY-MM-DD"), C("time", "время записи", "HH:MM"), C("distance_km", "дистанция", "км"),
    C("duration_sec", "время забега", "сек"), C("pace_sec_per_km", "темп", "сек/км"),
    C("speed_kmh", "скорость", "км/ч"),
))
HABITS = TableSpec("habits", "habits.csv", "Привычки", "одна запись привычки", (
    C("date", "день", "YYYY-MM-DD"), C("time", "время отметки", "HH:MM"), C("habit", "привычка"),
    C("type", "check — отметка, amount — количество, duration — длительность"),
    C("value", "значение отметки (для длительности — минуты)"), C("unit", "единица привычки"),
    C("daily_goal", "цель в день"),
))
BODY = TableSpec("weight", "body_weight.csv", "Вес тела", "одно взвешивание", (
    C("date", "день", "YYYY-MM-DD"), C("weight_kg", "вес", "кг"),
))
GOALS = TableSpec("goals", "goals.csv", "Цели КБЖУ", "одна цель КБЖУ (действует с start_date до следующей)", (
    C("start_date", "с какого дня действует", "YYYY-MM-DD"), C("mode", "gain — набор, maintain — поддержание, "
                                                                   "loss — снижение"),
    C("kcal", "калории", "ккал"), C("protein", "белки", "г"), C("fat", "жиры", "г"), C("carbs", "углеводы", "г"),
    C("target_weight", "целевой вес", "кг"), C("source", "calc — рассчитана, manual — вручную, text — текстом"),
))
PROFILE = TableSpec("profile", "profile.csv", "Профиль", "одна строка — профиль без имени", (
    C("sex", "male / female"), C("age", "возраст", "лет"), C("height_cm", "рост", "см"),
    C("weight_kg", "вес в профиле", "кг"), C("activity", "активность: minimal, light, medium, high, very_high"),
    C("goal", "gain — набор, maintain — поддержание, loss — снижение"), C("target_weight", "целевой вес", "кг"),
    C("experience", "опыт тренировок: beginner, intermediate, advanced"), C("city", "город"),
))

TABLES = (DAILY, FOOD, WARMUPS, WORKOUTS, RUNS, HABITS, BODY, GOALS, PROFILE)
BY_KEY = {t.key: t for t in TABLES}
