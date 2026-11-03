#!/usr/bin/env bash
# Проверяет, что секреты заданы; печатает понятный список недостающих (код SECRET-MISSING).
# Использование: scripts/require_secrets.sh ИМЯ… (значения — в переменных окружения с теми же именами)
set -u
missing=0
for name in "$@"; do
  if [ -z "${!name:-}" ]; then
    python3 -m habit_bot.ops render SECRET-MISSING "name=$name"
    missing=1
  fi
done
if [ "$missing" = 1 ]; then
  {
    echo "### Не хватает секретов"
    for name in "$@"; do [ -z "${!name:-}" ] && echo "- \`$name\` — Settings → Secrets and variables → Actions → New repository secret"; done
  } >> "${GITHUB_STEP_SUMMARY:-/dev/null}"
fi
exit "$missing"
