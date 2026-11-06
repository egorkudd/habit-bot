#!/usr/bin/env bash
# Выкладка без GitHub Actions: запускает владелец со своего компьютера одной командой
#   ssh -i deploy_key deploy@IP 'curl -fsSL https://raw.githubusercontent.com/egorkudd/habit-bot/main/deploy/update.sh | bash'
# На сервере: свежий main с GitHub → сборка образа → те же шаги, что у «Выкладки» (remote.sh deploy: проверка
# настроек, бэкап, миграции, запуск, проверка здоровья, откат при сбое) → сообщение администраторам в Telegram.
# Настройки (.env) остаются прежними; токен и пароли никуда не передаются.
# Для приватного репозитория: GH_TOKEN=… (токен только на чтение) перед командой.
set -euo pipefail

REPO=egorkudd/habit-bot
REF=${1:-main}
APP=/srv/bot/app
SRC=/srv/bot/src
REPO_IMAGE=ghcr.io/egorkudd/habit-bot

say() { echo "▶ $*"; }
auth=()
[ -n "${GH_TOKEN:-}" ] && auth=(-H "Authorization: Bearer $GH_TOKEN")

say "Код ветки $REF с GitHub"
sha=$(curl -fsSL "${auth[@]}" -H "Accept: application/vnd.github.sha" "https://api.github.com/repos/$REPO/commits/$REF")
rm -rf "$SRC" && mkdir -p "$SRC"
curl -fsSL "${auth[@]}" "https://api.github.com/repos/$REPO/tarball/$sha" | tar -xz -C "$SRC" --strip-components=1
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$SRC/habit_bot/__init__.py")
image="$REPO_IMAGE:$version-${sha:0:7}"
say "Версия $version ($image)"

say "Сборка образа"
docker build -q -t "$image" --build-arg VERSION="$version" "$SRC" >/dev/null

say "Файлы выкладки"
cp -f "$SRC/deploy/docker-compose.yml" "$SRC/deploy/remote.sh" "$SRC/deploy/update.sh" "$APP/"
cp -f "$APP/.env" "$APP/.env.new"  # настройки прежние: секреты в GitHub сейчас недоступны

say "Бэкап, миграции, запуск, проверка здоровья"
log=$(mktemp)
set +e
bash "$APP/remote.sh" deploy "$image" "$version" </dev/null 2>&1 | tee "$log"
code=${PIPESTATUS[0]}
set -e
rm -rf "$SRC"

# Сообщение администраторам — тем же ботом, что и раньше сообщала «Выкладка».
set -a; . "$APP/.env"; set +a
if [ "$code" -eq 0 ]; then
  text="✅ Версия $version выложена (с сервера, без GitHub Actions)."
else
  last=$(grep '^RESULT' "$log" | tail -1)
  text="❌ Выкладка $version не удалась: ${last#RESULT }. Подробности — в выводе команды."
fi
rm -f "$log"
proxy=()
[ -n "${TELEGRAM_PROXY:-}" ] && proxy=(-x "$TELEGRAM_PROXY")
for chat in ${ADMIN_TG_IDS//,/ }; do
  curl -fsS "${proxy[@]}" -o /dev/null "https://api.telegram.org/bot$BOT_TOKEN/sendMessage" \
    --data-urlencode "chat_id=$chat" --data-urlencode "text=$text" || true
done
exit "$code"
