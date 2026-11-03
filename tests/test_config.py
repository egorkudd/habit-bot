"""Раздел 7.4.3: при старте проверяются все настройки сразу, выводится полный список проблем."""

from decimal import Decimal
from pathlib import Path

import pytest

from habit_bot.kernel.config import ConfigError, load_settings
from habit_bot.modules import KNOWN_MODULES
from tests.conftest import ADMIN_ID, TOKEN


def _errors(env: dict[str, str], known: tuple[str, ...] = tuple(KNOWN_MODULES)) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        load_settings(env, known)
    return info.value


def test_valid_settings_and_defaults(base_env: dict[str, str]) -> None:
    """Корректные настройки читаются; модули, каналы и бюджет ИИ — по умолчанию."""
    settings = load_settings(base_env, KNOWN_MODULES)
    assert settings.admin_tg_ids == frozenset({ADMIN_ID})
    assert settings.bot_token == TOKEN
    assert settings.enabled_modules == ("users",)
    assert settings.enabled_channels == ("telegram",)
    assert settings.llm_monthly_budget_usd == Decimal("5")
    assert settings.db_path == Path(base_env["DATA_DIR"]) / "bot.db"
    assert settings.database_url == f"sqlite+aiosqlite:///{Path(base_env['DATA_DIR']) / 'bot.db'}"
    assert settings.sync_database_url == f"sqlite:///{Path(base_env['DATA_DIR']) / 'bot.db'}"


def test_empty_admins_and_bad_token_reported_together(base_env: dict[str, str]) -> None:
    """Раздел 9: пустой ADMIN_TG_IDS и неверный BOT_TOKEN одновременно → оба пункта с подсказками."""
    err = _errors({**base_env, "ADMIN_TG_IDS": "", "BOT_TOKEN": "abc"})
    assert err.codes == ["CFG-ADMIN", "CFG-TOKEN"]
    report = err.report().splitlines()
    assert report[0] == "Бот не запущен — исправьте настройки (Settings → Secrets and variables → Actions):"
    assert report[1] == (
        "1. CFG-ADMIN: ADMIN_TG_IDS пуст — добавьте свой Telegram-ID в секрет ADMIN_TG_IDS (узнать: @userinfobot)."
    )
    assert report[2].startswith("2. CFG-TOKEN: BOT_TOKEN не похож на токен")
    assert "@BotFather" in report[2]


def test_every_problem_listed(base_env: dict[str, str]) -> None:
    """Все проблемы сразу: токен, ID, пароль бэкапов, модули, каналы, прокси, ИИ, число."""
    env = {
        "ADMIN_TG_IDS": "123,abc",
        "BACKUP_PASSWORD": "short",
        "ENABLED_MODULES": "users,ai_commands,food",
        "ENABLED_CHANNELS": "telegram,fax",
        "TELEGRAM_PROXY": "ftp://proxy",
        "LLM_MONTHLY_BUDGET_USD": "много",
    }
    err = _errors(env, known=("users", "ai_commands"))
    assert err.codes == [
        "CFG-ADMIN", "CFG-TOKEN", "CFG-BACKUP", "CFG-MODULES", "CFG-MODULES", "CFG-PROXY", "CFG-LLM", "CFG-NUMBER",
    ]
    text = err.report()
    assert "«abc» не похоже на Telegram-ID" in text
    assert "BOT_TOKEN не задан" in text
    assert "неизвестные модули «food»" in text
    assert "оставьте только известные значения: users, ai_commands" in text
    assert "неизвестные каналы «fax»" in text
    assert "не заданы LLM_BASE_URL, LLM_MODEL, LLM_API_KEY" in text


def test_missing_backup_password(base_env: dict[str, str]) -> None:
    """Без пароля бэкапов бот не запускается."""
    env = dict(base_env)
    del env["BACKUP_PASSWORD"]
    assert _errors(env).codes == ["CFG-BACKUP"]


def test_llm_settings_needed_only_with_ai_module(base_env: dict[str, str]) -> None:
    """До части 9 бот запускается без ключа DeepSeek; с модулем ИИ ключ обязателен."""
    assert load_settings(base_env, KNOWN_MODULES).llm_api_key is None
    env = {
        **base_env, "ENABLED_MODULES": "users,ai_commands", "LLM_BASE_URL": "https://api.deepseek.com",
        "LLM_MODEL": "deepseek-flash", "LLM_API_KEY": "sk-test", "LLM_MONTHLY_BUDGET_USD": "7,5",
        "TELEGRAM_PROXY": "socks5://127.0.0.1:1080", "BOT_API_BASE": "http://127.0.0.1:8081", "LOG_LEVEL": "debug",
    }
    settings = load_settings(env, ("users", "ai_commands"))
    assert settings.llm_monthly_budget_usd == Decimal("7.5")
    assert settings.telegram_proxy == "socks5://127.0.0.1:1080"
    assert settings.bot_api_base == "http://127.0.0.1:8081"
    assert settings.log_level == "DEBUG"
