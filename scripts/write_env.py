"""Собирает .env для сервера из секретов GitHub (раздел 7.3): ``python scripts/write_env.py > .env.new``.

Значения пишутся в одинарных кавычках — docker compose читает их буквально, без подстановок ``$``.
Значение с одинарной кавычкой или переводом строки записать так нельзя — сценарий остановится с подсказкой.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Mapping

KEYS = (
    "BOT_TOKEN",
    "ADMIN_TG_IDS",
    "BACKUP_PASSWORD",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_API_KEY",
    "LLM_MONTHLY_BUDGET_USD",
    "LLM_FALLBACK_BASE_URL",
    "LLM_FALLBACK_MODEL",
    "LLM_FALLBACK_API_KEY",
    "TELEGRAM_PROXY",
    "ENABLED_MODULES",
    "ENABLED_CHANNELS",
    "LOG_LEVEL",
)


def render(env: Mapping[str, str]) -> str:
    lines = ["# Создано «Выкладкой» из GitHub Secrets. Не редактировать вручную.", "DATA_DIR='/data'"]
    bad = [key for key in KEYS if any(ch in env.get(key, "") for ch in "'\n\r")]
    if bad:
        raise ValueError(
            f"Секреты {', '.join(bad)} содержат одинарную кавычку или перевод строки — "
            "задайте их заново без этих символов"
        )
    for key in KEYS:
        value = env.get(key, "").strip()
        if value:
            lines.append(f"{key}='{value}'")
    return "\n".join(lines) + "\n"


def main(env: Mapping[str, str] | None = None) -> int:
    try:
        sys.stdout.write(render(os.environ if env is None else env))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
