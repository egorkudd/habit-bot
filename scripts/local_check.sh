#!/usr/bin/env bash
# «Проверка» без GitHub Actions (раздел 7.3): те же 7 шагов на машине разработчика или Claude.
#   bash scripts/local_check.sh [ветка-сравнения]   — по умолчанию origin/main
# Сводка — в конце; код выхода 0, только если прошли все шаги.
set -uo pipefail

base=${1:-origin/main}
report=$(mktemp)
fail=0
run() {  # run «название» команда…
  local name="$1"; shift
  echo "━━ $name"
  if "$@"; then echo "✅ $name" >> "$report"; else echo "❌ $name" >> "$report"; fail=1; fi
}

run "1. Линтер: ruff" ruff check habit_bot tests scripts
mypy_check() {  # MYPY_IGNORE — регулярное выражение для ложных ошибок другой версии библиотек (по умолчанию пусто)
  local out
  out=$(mypy habit_bot scripts 2>&1 | grep 'error:' || true)
  [ -n "${MYPY_IGNORE:-}" ] && out=$(echo "$out" | grep -Ev "$MYPY_IGNORE" || true)
  [ -n "$out" ] && echo "$out" && return 1
  echo "mypy: ошибок нет"
}
run "1. Линтер: mypy" mypy_check
run "1. Линтер: границы модулей" python scripts/check_boundaries.py
rm -f .coverage .coverage.*
run "2–3. Все тесты (с поведенческими сценариями и фоновыми задачами)" \
  python -m pytest -q -p no:cacheprovider tests --cov --cov-report=
coverage json -q -o coverage.json
run "4. Покрытие: пороги" python scripts/coverage_gate.py coverage.json
run "4. Покрытие нового кода против $base" python scripts/diff_coverage.py coverage.json "$base"
run "5. Миграции" bash scripts/check_migrations.sh
if docker info >/dev/null 2>&1 && bash scripts/smoke_test.sh; then
  echo "✅ 6. Пробный запуск (Docker)" >> "$report"
else
  run "6. Пробный запуск (без Docker)" bash scripts/smoke_local.sh
fi
run "7. Поиск секретов" python scripts/find_secrets.py
rm -f coverage.json

echo; echo "━━ Итог «Проверки»"; cat "$report"; rm -f "$report"
exit "$fail"
