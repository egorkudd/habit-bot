#!/usr/bin/env bash
# Пробный запуск без Docker (шаг 6 «Проверки», когда образ собрать негде): бот стартует с тестовыми настройками
# на поддельном Telegram (scripts/fake_bot_api.py), проверка здоровья проходит за 30 секунд.
set -euo pipefail

data=$(mktemp -d)
python scripts/fake_bot_api.py --port 8082 &
api_pid=$!
bot_pid=""
# shellcheck disable=SC2317  # функция вызывается через trap
cleanup() {
  [ -n "$bot_pid" ] && kill "$bot_pid" 2>/dev/null || true
  kill "$api_pid" 2>/dev/null || true
  rm -rf "$data"
}
trap cleanup EXIT

export DATA_DIR="$data" ADMIN_TG_IDS=1 BACKUP_PASSWORD=ci-backup-password BOT_API_BASE=http://127.0.0.1:8082
BOT_TOKEN="123456789:$(printf 'A%.0s' {1..35})"  # поддельный — собирается здесь, чтобы не походить на секрет
export BOT_TOKEN
python -m habit_bot.ops migrate
python -m habit_bot >"$data/bot.log" 2>&1 &
bot_pid=$!

out=""
for second in $(seq 1 30); do
  if out=$(python -m habit_bot.health --full 2>&1); then
    echo "$out"
    echo "✅ Проверка здоровья прошла за ${second} с"
    exit 0
  fi
  sleep 1
done
echo "$out"
echo "❌ Проверка здоровья не прошла за 30 секунд. Лог бота:"
tail -80 "$data/bot.log"
exit 1
