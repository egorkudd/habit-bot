"""Настройки из переменных окружения (.env создаётся при выкладке из GitHub Secrets).

При старте проверяются все настройки сразу, и выводится полный список проблем (раздел 7.4.3).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from habit_bot.kernel.domain.config_rules import (
    is_valid_proxy,
    looks_like_bot_token,
    mask_secret,
    parse_id_list,
    parse_positive_decimal,
    split_list,
)
from habit_bot.kernel.errors.catalog import report_line

KNOWN_CHANNELS = ("telegram",)
MODULES_NEEDING_LLM = frozenset({"ai_commands"})
MIN_BACKUP_PASSWORD = 12


@dataclass(frozen=True, slots=True)
class ConfigProblem:
    code: str
    detail: str
    params: Mapping[str, str] = field(default_factory=dict)

    def line(self) -> str:
        return report_line(self.code, {"detail": self.detail, **self.params})


class ConfigError(Exception):
    """Настройки с ошибками: бот не запускается, а список уходит в лог и отчёт «Выкладки»."""

    def __init__(self, problems: list[ConfigProblem]) -> None:
        super().__init__(f"{len(problems)} проблем с настройками")
        self.problems = problems

    @property
    def codes(self) -> list[str]:
        return [p.code for p in self.problems]

    def report(self) -> str:
        lines = ["Бот не запущен — исправьте настройки (Settings → Secrets and variables → Actions):"]
        lines += [f"{n}. {p.line()}" for n, p in enumerate(self.problems, start=1)]
        return "\n".join(lines)


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_tg_ids: frozenset[int]
    backup_password: str
    data_dir: Path
    database_url: str
    enabled_modules: tuple[str, ...]
    enabled_channels: tuple[str, ...]
    bot_api_base: str | None = None
    telegram_proxy: str | None = None
    log_level: str = "INFO"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_api_key: str | None = None
    llm_monthly_budget_usd: Decimal = Decimal("5")
    llm_fallback_base_url: str | None = None
    llm_fallback_model: str | None = None
    llm_fallback_api_key: str | None = None

    @property
    def db_path(self) -> Path:
        return self.data_dir / "bot.db"

    @property
    def sync_database_url(self) -> str:
        """URL для Alembic и проверок здоровья (синхронный драйвер)."""
        return self.database_url.replace("+aiosqlite", "")


def _get(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def load_settings(env: Mapping[str, str], known_modules: Iterable[str]) -> Settings:
    """Читает и проверяет настройки. При любых проблемах бросает ``ConfigError`` со всем списком."""
    problems: list[ConfigProblem] = []
    known = tuple(known_modules)

    admin_ids, bad_ids = parse_id_list(_get(env, "ADMIN_TG_IDS"))
    if bad_ids:
        problems.append(ConfigProblem(
            "CFG-ADMIN", f"ADMIN_TG_IDS: «{', '.join(bad_ids)}» не похоже на Telegram-ID — нужны числа через запятую",
        ))
    elif not admin_ids:
        problems.append(ConfigProblem("CFG-ADMIN", "ADMIN_TG_IDS пуст"))

    token = _get(env, "BOT_TOKEN")
    if token is None:
        problems.append(ConfigProblem("CFG-TOKEN", "BOT_TOKEN не задан"))
    elif not looks_like_bot_token(token):
        problems.append(ConfigProblem(
            "CFG-TOKEN", f"BOT_TOKEN не похож на токен ({mask_secret(token)}, ожидается 123456789:AA…)",
        ))

    backup_password = _get(env, "BACKUP_PASSWORD")
    if backup_password is None:
        problems.append(ConfigProblem("CFG-BACKUP", "BACKUP_PASSWORD не задан"))
    elif len(backup_password) < MIN_BACKUP_PASSWORD:
        problems.append(ConfigProblem(
            "CFG-BACKUP", f"BACKUP_PASSWORD короче {MIN_BACKUP_PASSWORD} символов",
        ))

    explicit_modules = split_list(env.get("ENABLED_MODULES"))
    modules = explicit_modules or known  # по умолчанию включены все модули
    unknown_modules = [m for m in modules if m not in known]
    if unknown_modules:
        problems.append(ConfigProblem(
            "CFG-MODULES", f"ENABLED_MODULES: неизвестные модули «{', '.join(unknown_modules)}»",
            {"known": ", ".join(known)},
        ))

    channels = split_list(env.get("ENABLED_CHANNELS")) or ("telegram",)
    unknown_channels = [c for c in channels if c not in KNOWN_CHANNELS]
    if unknown_channels:
        problems.append(ConfigProblem(
            "CFG-MODULES", f"ENABLED_CHANNELS: неизвестные каналы «{', '.join(unknown_channels)}»",
            {"known": ", ".join(KNOWN_CHANNELS)},
        ))

    proxy = _get(env, "TELEGRAM_PROXY")
    if proxy is not None and not is_valid_proxy(proxy):
        problems.append(ConfigProblem("CFG-PROXY", f"TELEGRAM_PROXY: «{mask_secret(proxy)}» — неизвестная схема"))

    llm_base_url = _get(env, "LLM_BASE_URL")
    llm_model = _get(env, "LLM_MODEL")
    llm_api_key = _get(env, "LLM_API_KEY")
    # Ключ модели обязателен, только если модуль ИИ включён явно. По умолчанию (все модули) бот работает и без
    # ключа: разбор текстом выключен, кнопки — как обычно (раздел 7.2, «при нулевом балансе — только кнопки»).
    if MODULES_NEEDING_LLM.intersection(explicit_modules):
        missing = [
            name for name, value in
            (("LLM_BASE_URL", llm_base_url), ("LLM_MODEL", llm_model), ("LLM_API_KEY", llm_api_key))
            if value is None
        ]
        if missing:
            problems.append(ConfigProblem("CFG-LLM", f"не заданы {', '.join(missing)}"))

    budget = Decimal("5")
    raw_budget = _get(env, "LLM_MONTHLY_BUDGET_USD")
    if raw_budget is not None:
        parsed = parse_positive_decimal(raw_budget)
        if parsed is None:
            problems.append(ConfigProblem(
                "CFG-NUMBER", f"LLM_MONTHLY_BUDGET_USD: «{raw_budget}» — не положительное число",
            ))
        else:
            budget = parsed

    if problems:
        raise ConfigError(problems)

    data_dir = Path(_get(env, "DATA_DIR") or "/data")
    database_url = _get(env, "DATABASE_URL") or f"sqlite+aiosqlite:///{data_dir / 'bot.db'}"
    assert token is not None and backup_password is not None  # проверено выше
    return Settings(
        bot_token=token,
        admin_tg_ids=admin_ids,
        backup_password=backup_password,
        data_dir=data_dir,
        database_url=database_url,
        enabled_modules=modules,
        enabled_channels=channels,
        bot_api_base=_get(env, "BOT_API_BASE"),
        telegram_proxy=proxy,
        log_level=(_get(env, "LOG_LEVEL") or "INFO").upper(),
        llm_base_url=llm_base_url,
        llm_model=llm_model,
        llm_api_key=llm_api_key,
        llm_monthly_budget_usd=budget,
        llm_fallback_base_url=_get(env, "LLM_FALLBACK_BASE_URL"),
        llm_fallback_model=_get(env, "LLM_FALLBACK_MODEL"),
        llm_fallback_api_key=_get(env, "LLM_FALLBACK_API_KEY"),
    )
