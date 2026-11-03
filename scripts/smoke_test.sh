#!/usr/bin/env bash
# Шаг «6. Пробный запуск» (раздел 7.3): контейнер стартует с тестовыми настройками,
# проверка здоровья проходит за 30 секунд. Telegram поддельный (scripts/fake_bot_api.py) — без сети.
set -euo pipefail

image=habit-bot:ci
name=habit-smoke
data=$(mktemp -d)
chmod 777 "$data"

docker build -q -t "$image" --build-arg VERSION=ci . >/dev/null
python scripts/fake_bot_api.py --port 8081 &
api_pid=$!
cleanup() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  kill "$api_pid" 2>/dev/null || true
  rm -rf "$data"
}
trap cleanup EXIT

# Поддельный токен собирается здесь, чтобы поиск секретов не принял его за настоящий.
token="123456789:$(printf 'A%.0s' $(seq 35))"
common=(--network host --user "$(id -u):$(id -g)" -v "$data:/data" -e DATA_DIR=/data)

docker run --rm "${common[@]}" "$image" python -m habit_bot.ops migrate
docker run -d --name "$name" "${common[@]}" \
  -e BOT_TOKEN="$token" -e ADMIN_TG_IDS=1 -e BACKUP_PASSWORD=ci-backup-password \
  -e BOT_API_BASE=http://127.0.0.1:8081 "$image" >/dev/null

out=""
for second in $(seq 1 30); do
  if out=$(docker exec "$name" python -m habit_bot.health --full 2>&1); then
    echo "$out"
    echo "✅ Проверка здоровья прошла за ${second} с"
    exit 0
  fi
  sleep 1
done
echo "$out"
echo "❌ Проверка здоровья не прошла за 30 секунд. Лог контейнера:"
docker logs --tail 80 "$name"
exit 1
