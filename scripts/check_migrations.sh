#!/usr/bin/env bash
# Шаг «5. Миграции» (раздел 7.3): пустая база, откат и подъём, совпадение схемы с моделями,
# подъём с копии схемы предыдущей версии (ветка main).
set -euo pipefail
work=$(mktemp -d)
cleanup() { git worktree remove --force "$work/prev" >/dev/null 2>&1 || true; rm -rf "$work"; }
trap cleanup EXIT

echo "▶ Пустая база: upgrade head"
DATA_DIR="$work/fresh" python -m habit_bot.ops migrate

echo "▶ downgrade -1 → upgrade head → схема совпадает с моделями (alembic check)"
DATA_DIR="$work/fresh" python - <<'PY'
import os
from alembic import command
from habit_bot.kernel.migrations import alembic_config

cfg = alembic_config(f"sqlite:///{os.environ['DATA_DIR']}/bot.db")
command.downgrade(cfg, "-1")
command.upgrade(cfg, "head")
command.check(cfg)
PY

echo "▶ Копия схемы предыдущей версии (origin/main)"
if git rev-parse --verify -q origin/main >/dev/null && git cat-file -e origin/main:habit_bot/migrations 2>/dev/null; then
  git worktree add -q --detach "$work/prev" origin/main
  (cd "$work/prev" && DATA_DIR="$work/prev-data" python -m habit_bot.ops migrate)
  DATA_DIR="$work/prev-data" python -m habit_bot.ops migrate
else
  echo "  в main ещё нет миграций — пропущено"
fi
echo "✅ Миграции в порядке"
