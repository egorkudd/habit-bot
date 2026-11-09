"""30 эталонных фраз (раздел 9): фраза → ответ модели → что бот покажет в карточке «Понял так».

Ответы записаны вручную по инструкции из ``prompt.py``: на дату записи ключа модели у владельца ещё нет.
Когда ключ появится, задание CI «Внешние сервисы» прогонит эти фразы на настоящей модели и проверит, что не меньше
27 из 30 разобраны так же (``tests/live/test_llm_live.py``; вручную — ``LIVE_SERVICES=1 LLM_BASE_URL=… LLM_MODEL=…
LLM_API_KEY=… pytest tests/live/test_llm_live.py``).
"""

from __future__ import annotations

from typing import Any

D = "2026-11-03"
Y = "2026-11-02"


def _a(**kw: Any) -> dict[str, Any]:
    return kw


GOLDEN: list[dict[str, Any]] = [
    {"phrase": "вчера на обед было 2 бедра и пакет гречи, а коктейль сегодня удали", "reply": {"actions": [
        _a(type="food.add", day=Y, item="Куриное бедро", quantity=2),
        _a(type="food.add", day=Y, item="Гречка сухая (пакет 80 г)", quantity=1),
        _a(type="food.delete", day=D, item="Коктейль")]},
     "expect": ["➕ 02.11 Еда: Куриное бедро × 2 — 500 ккал", "➕ 02.11 Еда: Гречка сухая (пакет 80 г) — 288,8 ккал",
                "🗑 03.11 Еда: Коктейль (09:12)"]},
    {"phrase": "планку сегодня во 2-й зарядке делал 6:15, а не 6:00", "reply": {"actions": [
        _a(type="warmup.edit", day=D, number=2, exercise="Планка", value="6:15")]},
     "expect": ["✏️ 03.11 Зарядка 2-я: Планка 6:00 → 6:15"]},
    {"phrase": "глаза сделал 2 раза, воды 5 стаканов", "reply": {"actions": [
        _a(type="habit.mark", day=D, habit="Глаза", times=2),
        _a(type="habit.value", day=D, habit="Вода", value=5)]},
     "expect": ["✅ 03.11 👁 Глаза ×2", "➕ 03.11 💧 Вода +5 стак."]},
    {"phrase": "пробежал 5,2 км за 28:40", "reply": {"actions": [
        _a(type="run.add", day=D, distance_km=5.2, time="28:40")]},
     "expect": ["🏃 03.11 5,2 км · 28:40 · темп 5:31"]},
    {"phrase": "перенеси творог ужин на вчера", "reply": {"actions": [
        _a(type="food.move", day=D, item="Творог ужин", to_day=Y)]},
     "expect": ["📅 03.11 → 02.11 Еда: Творог ужин"]},
    {"phrase": "съел 250 г пельменей", "reply": {"actions": [
        _a(type="food.add", day=D, item="Пельмени", quantity=250)]},
     "expect": ["➕ 03.11 Еда: Пельмени 250 г — 650 ккал"]},
    {"phrase": "коктейль сегодня был двойной", "reply": {"actions": [
        _a(type="food.quantity", day=D, item="Коктейль", quantity=2)]},
     "expect": ["✏️ 03.11 Еда: Коктейль (09:12) — 1 → 2"]},
    {"phrase": "вчера был выходной", "reply": {"actions": [_a(type="day.off", day=Y)]},
     "expect": ["🛌 02.11 Выходной"]},
    {"phrase": "вес 77,5", "reply": {"actions": [_a(type="weight.record", day=D, kg=77.5)]},
     "expect": ["⚖️ 03.11 Вес 77,5 кг"]},
    {"phrase": "зарядка: отжимания 55, мостик 50, планка 6:00, спина 30", "reply": {"actions": [
        _a(type="warmup.add", day=D, values={"Отжимания": "55", "Мостик": "50", "Планка": "6:00", "Спина": "30"})]},
     "expect": ["➕ 03.11 Зарядка: Отжимания 55 · Мостик 50 · Планка 6:00 · Спина 30"]},
    {"phrase": "присед 110 на 4 по 8", "reply": {"actions": [
        _a(type="workout.set", day=D, exercise="Присед со штангой", weight=110, reps=[8, 8, 8, 8])]},
     "expect": ["🏋️ 03.11 Присед со штангой: 110 кг 4×8"]},
    {"phrase": "жим лёжа 80 кг 8 8 7 6", "reply": {"actions": [
        _a(type="workout.set", day=D, exercise="Жим лёжа", weight=80, reps=[8, 8, 7, 6])]},
     "expect": ["🏋️ 03.11 Жим лёжа: 80 кг 8, 8, 7, 6"]},
    {"phrase": "планка в зале 3 подхода по 45 секунд", "reply": {"actions": [
        _a(type="workout.set", day=D, exercise="Планка", seconds=[45, 45, 45])]},
     "expect": ["🏋️ 03.11 Планка: 3×0:45"]},
    {"phrase": "выпил витамины", "reply": {"actions": [_a(type="habit.mark", day=D, habit="Витамины")]},
     "expect": ["✅ 03.11 💊 Витамины ×1"]},
    {"phrase": "прошёл 8500 шагов", "reply": {"actions": [_a(type="habit.value", day=D, habit="Шаги", value=8500)]},
     "expect": ["➕ 03.11 🚶 Шаги +8 500 шагов"]},
    {"phrase": "на ужин была шаурма", "reply": {"actions": [
        _a(type="food.add", day=D, item="Шаурма", kcal=650, protein=30, fat=35, carbs=55)]},
     "expect": ["➕ 03.11 Еда: Шаурма ≈ 650 ккал · Б 30 · Ж 35 · У 55 (оценка модели)"]},
    {"phrase": "удали творог ужин", "reply": {"actions": [_a(type="food.delete", day=D, item="Творог ужин")]},
     "expect": ["🗑 03.11 Еда: Творог ужин (12:30)"]},
    {"phrase": "вчера пробежал 10 км за 52 минуты", "reply": {"actions": [
        _a(type="run.add", day=Y, distance_km=10, time="52")]},
     "expect": ["🏃 02.11 10,0 км · 52:00 · темп 5:12"]},
    {"phrase": "рецепт: Сырники — 350 ккал, Б 20, Ж 15, У 30, 120 ₽", "reply": {"actions": [
        _a(type="recipe.create", name="Сырники", kcal=350, protein=20, fat=15, carbs=30, price=120)]},
     "expect": ["🍽 Рецепт «Сырники»: 350 ккал · Б 20 · Ж 15 · У 30 · 120 ₽"]},
    {"phrase": "Коктейль теперь 330 ккал, Б 27, Ж 9, У 40, 150 ₽", "reply": {"actions": [
        _a(type="recipe.create", name="Коктейль", kcal=330, protein=27, fat=9, carbs=40, price=150)]},
     "expect": ["♻️ Рецепт «Коктейль» уже есть — обновлю: 330 ккал · Б 27 · Ж 9 · У 40 · 150 ₽"]},
    {"phrase": "добавь привычку чтение", "reply": {"actions": [_a(type="habit.create", name="Чтение")]},
     "expect": ["✅ Привычка «📖 Чтение», цель 20 мин"]},
    {"phrase": "новая привычка: медитация 15 минут в день", "reply": {"actions": [
        _a(type="habit.create", name="Медитация", emoji="🧘", measure="duration", goal=15)]},
     "expect": ["✅ Привычка «🧘 Медитация», цель 15 мин"]},
    {"phrase": "цель с 22.09: 2410 ккал, белки 140, жиры 70, углеводы 305", "reply": {"actions": [
        _a(type="goal.set", start_date="2026-09-22", kcal=2410, protein=140, fat=70, carbs=305)]},
     "expect": ["🎯 Цель КБЖУ с 22.09: 2 410 ккал · Б 140 · Ж 70 · У 305"]},
    {"phrase": "цель по планке 11:00 к 3 декабря", "reply": {"actions": [
        _a(type="exercise_goal.set", exercise="Планка", value="11:00", date="2026-12-03")]},
     "expect": ["🎯 Планка: 11:00 к 03.12.2026"]},
    {"phrase": "в зарядку добавь приседания с шагом 10", "reply": {"actions": [
        _a(type="warmup.set", exercises=[{"name": "Приседания", "measure": "reps", "step": 10}])]},
     "expect": ["🤸 Набор зарядки: Приседания (+10)"]},
    {"phrase": "творог", "reply": {"actions": [], "question": {"text": "Какой творог?",
                                                              "options": ["Творог ужин", "Творог 5%"]}},
     "expect": ["? Какой творог? [Творог ужин] [Творог 5%]"]},
    {"phrase": "как дела?", "reply": {"actions": []}, "expect": ["LLM-UNCLEAR"]},
    {"phrase": "завтра съем коктейль", "reply": {"actions": [
        _a(type="food.add", day="2026-11-04", item="Коктейль")]},
     "expect": ["× Коктейль: 04.11 — это будущее"]},
    {"phrase": "удали шаурму сегодня", "reply": {"actions": [_a(type="food.delete", day=D, item="Шаурма")]},
     "expect": ["× Еда: «Шаурма» за 03.11 не найдено"]},
    {"phrase": "напоминай про глаза каждый день в 12:00", "reply": {"actions": []}, "expect": ["LLM-UNCLEAR"]},
]
