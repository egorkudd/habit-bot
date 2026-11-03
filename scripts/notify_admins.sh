#!/usr/bin/env bash
# Оповещение администраторам в Telegram с серверов GitHub (работает, даже когда у VPS нет связи с Telegram).
# Использование: BOT_TOKEN=… ADMIN_TG_IDS=… scripts/notify_admins.sh "текст"
# Никогда не роняет сценарий: оповещение — не причина красной проверки.
set -u
text="${1:-}"
if [ -z "${BOT_TOKEN:-}" ] || [ -z "${ADMIN_TG_IDS:-}" ] || [ -z "$text" ]; then
  echo "Оповещение не отправлено: нет BOT_TOKEN, ADMIN_TG_IDS или текста"
  exit 0
fi
IFS=',' read -ra ids <<< "$ADMIN_TG_IDS"
for id in "${ids[@]}"; do
  id="${id// /}"
  [ -z "$id" ] && continue
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 \
    "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
    --data-urlencode "chat_id=${id}" --data-urlencode "text=${text}" \
    --data-urlencode "disable_web_page_preview=true" || echo 000)
  echo "Оповещение администратору ${id:0:3}…: HTTP $code"
done
exit 0
