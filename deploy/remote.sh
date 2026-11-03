#!/usr/bin/env bash
# Команды на сервере для сценариев GitHub Actions (раздел 7.3). Запускается от пользователя deploy.
#   remote.sh deploy IMAGE VERSION     — выкладка (токен ghcr.io и логин — в stdin, по строке)
#   remote.sh rollback [VERSION]       — откат на версию из истории (по умолчанию — предыдущую)
#   remote.sh health                   — проверка для «Бот жив?», перезапуск при сбое
#   remote.sh cleanup                  — удаление старых образов, кэша и временных файлов
# Последняя строка вывода — «RESULT …»: её разбирает сценарий.
set -uo pipefail

APP=/srv/bot/app
DATA=/srv/bot/data
REPO_IMAGE=ghcr.io/egorkudd/habit-bot
cd "$APP" || exit 1

export APP_UID APP_GID
APP_UID=$(id -u)
APP_GID=$(id -g)

step() { echo "STEP $1"; }
result() { echo "RESULT $*"; }
compose() { docker compose -f "$APP/docker-compose.yml" "$@"; }
use_image() { export BOT_IMAGE="$1" BOT_ENV_FILE="${2:-$APP/.env}"; }
current_image() { cat "$APP/current_image" 2>/dev/null || true; }
previous_image() { cat "$APP/previous_image" 2>/dev/null || true; }
version_of() { [ -n "$1" ] && grep -F " $1 " "$APP/releases.log" 2>/dev/null | tail -1 | cut -d' ' -f1; true; }
run_ops() { compose run --rm --no-deps -T bot python -m habit_bot.ops "$@"; }

health_wait() {
  # Проверка здоровья за 60 секунд: контейнер, база, миграции, отметка, getMe (раздел 7.3).
  local out=""
  for _ in $(seq 1 12); do
    if out=$(compose exec -T bot python -m habit_bot.health --full 2>&1); then
      echo "$out"
      return 0
    fi
    sleep 5
  done
  echo "$out"
  return 1
}

login_ghcr() {
  local token user
  read -r token || true
  read -r user || true
  [ -n "$token" ] && echo "$token" | docker login ghcr.io -u "$user" --password-stdin >/dev/null
}

prune_images() {
  # На сервере остаются только текущий и предыдущий образ (раздел 7, «Место на диске»).
  local keep
  keep=" $(current_image) $(previous_image) "
  docker image ls "$REPO_IMAGE" --format '{{.Repository}}:{{.Tag}}' | while read -r ref; do
    case "$keep" in *" $ref "*) ;; *) docker image rm "$ref" >/dev/null 2>&1 || true ;; esac
  done
  docker image prune -f >/dev/null 2>&1 || true
}

restore_and_restart() {
  # После сбоя: вернуть базу из бэкапа и запустить образ $1 (если есть).
  local image="$1"
  compose logs --no-color --tail 60 bot 2>/dev/null || true
  compose down --timeout 20 >/dev/null 2>&1 || true
  if [ -f "$DATA/backup/bot.db.bak" ]; then run_ops restore || true; fi
  [ -f "$APP/.env.prev" ] && mv -f "$APP/.env.prev" "$APP/.env"
  if [ -n "$image" ]; then
    use_image "$image"
    compose up -d >/dev/null 2>&1 && health_wait >/dev/null && return 0
  fi
  return 1
}

cmd_deploy() {
  local image="$1" version="$2" prev
  prev=$(current_image)

  step "Подготовка"
  login_ghcr
  if ! docker pull -q "$image"; then
    docker logout ghcr.io >/dev/null 2>&1
    result "fail step=Подготовка code=DEPLOY-FAIL rolled_back=none"
    return 1
  fi
  docker logout ghcr.io >/dev/null 2>&1

  step "Проверка настроек"
  use_image "$image" "$APP/.env.new"
  if ! run_ops check-config; then
    rm -f "$APP/.env.new"
    result "fail step=Проверка_настроек code=DEPLOY-CONFIG"
    return 1
  fi

  step "Бэкап"
  if ! run_ops backup; then
    rm -f "$APP/.env.new"
    result "fail step=Бэкап code=BKP-FAIL"
    return 1
  fi

  step "Остановка"
  if [ -n "$prev" ]; then
    use_image "$prev"
    compose down --timeout 30 || true
  fi
  [ -f "$APP/.env" ] && cp -f "$APP/.env" "$APP/.env.prev"
  mv -f "$APP/.env.new" "$APP/.env"
  use_image "$image"

  local failed=""
  step "Миграции"
  if ! run_ops migrate; then failed="Миграции"; fi
  if [ -z "$failed" ]; then
    step "Запуск"
    compose up -d || failed="Запуск"
  fi
  if [ -z "$failed" ]; then
    step "Проверка здоровья"
    health_wait || failed="Проверка здоровья"
  fi

  if [ -n "$failed" ]; then
    step "Откат"
    if restore_and_restart "$prev"; then
      result "fail step=${failed// /_} code=DEPLOY-FAIL rolled_back=$(version_of "$prev")"
    else
      result "fail step=${failed// /_} code=DEPLOY-FAIL rolled_back=none"
    fi
    return 1
  fi

  [ -n "$prev" ] && [ "$prev" != "$image" ] && echo "$prev" > "$APP/previous_image"
  echo "$image" > "$APP/current_image"
  echo "$version $image $(date -u +%Y-%m-%dT%H:%M:%SZ) deploy" >> "$APP/releases.log"
  rm -f "$APP/.env.prev"
  prune_images
  result "ok version=$version"
}

cmd_rollback() {
  local wanted="${1:-}" cur target target_head
  cur=$(current_image)
  if [ -n "$wanted" ]; then
    target=$(grep -E "^${wanted//./\\.} " "$APP/releases.log" 2>/dev/null | tail -1 | cut -d' ' -f2)
  else
    target=$(previous_image)
  fi
  if [ -z "$target" ] || [ "$target" = "$cur" ]; then
    echo "Доступные версии: $(cut -d' ' -f1 "$APP/releases.log" 2>/dev/null | tac | awk '!seen[$0]++' | head -3 | xargs)"
    result "fail step=Выбор_версии code=ROLLBACK-FAIL"
    return 1
  fi
  local version
  version=$(version_of "$target")

  step "Подготовка"
  login_ghcr
  docker pull -q "$target" >/dev/null || docker image inspect "$target" >/dev/null 2>&1 || {
    docker logout ghcr.io >/dev/null 2>&1
    result "fail step=Подготовка code=ROLLBACK-FAIL version=$version"
    return 1
  }
  docker logout ghcr.io >/dev/null 2>&1
  use_image "$target"
  target_head=$(run_ops migration-head | tail -1)

  step "Бэкап"
  use_image "$cur"
  run_ops backup || { result "fail step=Бэкап code=BKP-FAIL version=$version"; return 1; }

  step "Остановка"
  compose down --timeout 30 || true

  local failed=""
  step "Миграции"
  # Схему опускает текущий код: только он знает про свои новые миграции.
  run_ops migrate --to "$target_head" || failed="Миграции"
  if [ -z "$failed" ]; then
    use_image "$target"
    step "Запуск"
    compose up -d || failed="Запуск"
  fi
  if [ -z "$failed" ]; then
    step "Проверка здоровья"
    health_wait || failed="Проверка здоровья"
  fi
  if [ -n "$failed" ]; then
    step "Возврат"
    if restore_and_restart "$cur"; then
      result "fail step=${failed// /_} code=ROLLBACK-FAIL version=$version state=работает_прежняя_версия_$(version_of "$cur")"
    else
      result "fail step=${failed// /_} code=ROLLBACK-FAIL version=$version state=бот_остановлен"
    fi
    return 1
  fi
  echo "$cur" > "$APP/previous_image"
  echo "$target" > "$APP/current_image"
  echo "$version $target $(date -u +%Y-%m-%dT%H:%M:%SZ) rollback" >> "$APP/releases.log"
  prune_images
  result "ok version=$version"
}

cmd_health() {
  local image json="" restarted=0 restart_ok=0
  image=$(current_image)
  if [ -z "$image" ]; then
    result "skip reason=бот_ещё_не_выкладывался"
    return 0
  fi
  use_image "$image"
  if [ -n "$(compose ps --status running -q bot 2>/dev/null)" ]; then
    json=$(compose exec -T bot python -m habit_bot.health --full --json 2>/dev/null || true)
  fi
  [ -z "$json" ] && json='{}'
  echo "HEALTH $json"
  local parsed
  parsed=$(printf '%s' "$json" | python3 -c '
import json, sys
try:
    data = json.load(sys.stdin)
except ValueError:
    data = {}
checks = data.get("checks", {})
failed = [n for n, c in checks.items() if c.get("critical") and not c.get("ok")] if checks else ["container"]
print("ok=%d failed=%s tg=%d disk=%s mem=%s" % (
    1 if data.get("ok") else 0, ",".join(failed) or "-",
    1 if checks.get("telegram", {}).get("ok", True) else 0,
    checks.get("disk", {}).get("percent", "-"), checks.get("memory", {}).get("free_mb", "-")))
')
  if [[ "$parsed" == ok=0* ]]; then
    restarted=1
    compose up -d >/dev/null 2>&1 && compose restart bot >/dev/null 2>&1
    health_wait >/dev/null && restart_ok=1
  fi
  local disk
  disk=$(df --output=pcent "$DATA" | tail -1 | tr -dc '0-9')
  if [ "${disk:-0}" -ge 80 ]; then
    docker image prune -af --filter "until=24h" >/dev/null 2>&1 || true
    prune_images
    docker builder prune -af >/dev/null 2>&1 || true
    disk=$(df --output=pcent "$DATA" | tail -1 | tr -dc '0-9')
  fi
  result "$parsed restarted=$restarted restart_ok=$restart_ok host_disk=$disk"
}

cmd_cleanup() {
  local before after
  before=$(df --output=used -BM / | tail -1 | tr -dc '0-9')
  prune_images
  docker builder prune -af >/dev/null 2>&1 || true
  docker container prune -f >/dev/null 2>&1 || true
  find "$DATA/tmp" -type f -mmin +1440 ! -name heartbeat -delete 2>/dev/null || true
  after=$(df --output=used -BM / | tail -1 | tr -dc '0-9')
  result "ok freed_mb=$((before - after)) disk=$(df --output=pcent / | tail -1 | tr -dc '0-9')"
}

case "${1:-}" in
  deploy) shift; cmd_deploy "$@" ;;
  rollback) shift; cmd_rollback "$@" ;;
  health) cmd_health ;;
  cleanup) cmd_cleanup ;;
  *) echo "Использование: remote.sh deploy|rollback|health|cleanup" >&2; exit 2 ;;
esac
