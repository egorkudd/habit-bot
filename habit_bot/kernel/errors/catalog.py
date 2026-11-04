"""Каталог ошибок (раздел 7.4).

Каждое сообщение отвечает на три вопроса: что случилось, почему, что сделать.
Модуль без зависимостей: его используют и бот, и сценарии GitHub Actions
(``python -m habit_bot.ops render CODE``), и генератор таблицы в README.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Level(StrEnum):
    USER = "пользователю"
    ADMIN = "администратору"
    REPORT = "в отчёт и лог"


@dataclass(frozen=True, slots=True)
class ErrorSpec:
    code: str
    level: Level
    summary: str
    admin_text: str
    hint: str
    user_text: str = ""


class _Missing(dict[str, object]):
    def __missing__(self, key: str) -> str:
        return "?"


def _fill(template: str, params: Mapping[str, object]) -> str:
    return template.format_map(_Missing(params))


_SPECS: tuple[ErrorSpec, ...] = (
    # --- Настройки (раздел 7.4.3): попадают в лог контейнера и отчёт «Выкладки» ---
    ErrorSpec(
        "CFG-ADMIN", Level.REPORT, "Список администраторов пуст или неверен",
        "{detail}", "добавьте свой Telegram-ID в секрет ADMIN_TG_IDS (узнать: @userinfobot).",
    ),
    ErrorSpec(
        "CFG-TOKEN", Level.REPORT, "Токен бота не задан или не похож на токен",
        "{detail}", "скопируйте токен заново у @BotFather в секрет BOT_TOKEN.",
    ),
    ErrorSpec(
        "CFG-BACKUP", Level.REPORT, "Нет пароля для шифрования бэкапов",
        "{detail}",
        "задайте в секрете BACKUP_PASSWORD пароль не короче 12 символов и сохраните его в менеджере паролей.",
    ),
    ErrorSpec(
        "CFG-LLM", Level.REPORT, "Не хватает настроек языковой модели",
        "{detail}",
        "для DeepSeek: LLM_BASE_URL=https://api.deepseek.com, LLM_MODEL и LLM_API_KEY — раздел 7.2.",
    ),
    ErrorSpec(
        "CFG-NUMBER", Level.REPORT, "В настройке ожидалось положительное число",
        "{detail}", "укажите положительное число, например 5.",
    ),
    ErrorSpec(
        "CFG-MODULES", Level.REPORT, "Неизвестный модуль или канал в настройках",
        "{detail}", "оставьте только известные значения: {known}.",
    ),
    ErrorSpec(
        "CFG-PROXY", Level.REPORT, "Адрес прокси для Telegram записан неверно",
        "{detail}", "адрес должен начинаться с http://, https:// или socks5:// (секрет TELEGRAM_PROXY).",
    ),
    # --- Пользователю (раздел 7.4.1) ---
    ErrorSpec(
        "ACCESS-NO-INVITE", Level.USER, "Вход без приглашения",
        "Попытка входа без приглашения", "попросите ссылку-приглашение у администратора.",
        user_text="Бот доступен по приглашению. Если у вас есть ссылка — откройте её ещё раз",
    ),
    ErrorSpec(
        "ACCESS-INVITE-EXPIRED", Level.USER, "Приглашение истекло, исчерпано или отозвано",
        "Вход по недействующему приглашению", "попросите новую ссылку у того, кто её прислал.",
        user_text="Эта ссылка больше не действует ({reason}). Попросите новую у того, кто её прислал",
    ),
    ErrorSpec(
        "ACCESS-BLOCKED", Level.USER, "Пользователь заблокирован",
        "Вход заблокированного пользователя", "обратитесь к администратору.",
        user_text="Доступ к боту закрыт. Обратитесь к администратору",
    ),
    ErrorSpec(
        "ACCESS-LAST-ADMIN", Level.USER, "Единственный администратор удаляет аккаунт",
        "Попытка удалить аккаунт последнего администратора",
        "сначала добавьте ещё один Telegram-ID в секрет ADMIN_TG_IDS и перезапустите бота «Выкладкой».",
        user_text=(
            "Вы единственный администратор — аккаунт удалить нельзя. "
            "Сначала добавьте ещё один Telegram-ID в секрет ADMIN_TG_IDS"
        ),
    ),
    ErrorSpec(
        "ACCESS-FOREIGN", Level.USER, "Нажата чужая или подменённая кнопка",
        "Кнопка с чужими данными отклонена", "ничего делать не нужно; если повторяется — сообщите Claude.",
        user_text="Эта кнопка не ваша — ничего не изменено. Вот главное меню 👇",
    ),
    ErrorSpec(
        "INPUT-NUMBER", Level.USER, "Не число",
        "Ввод не похож на число", "напишите число с точкой или запятой, например 4,5 или 4.5.",
        user_text="Не понял число „{value}“. Напишите, например, 4,5 или 4.5",
    ),
    ErrorSpec(
        "INPUT-RANGE", Level.USER, "Число вне допустимых границ",
        "Число вне диапазона", "введите значение в указанных границах.",
        user_text="{field} — от {low} до {high}{unit}. Вы ввели {value}{guess}",
    ),
    ErrorSpec(
        "INPUT-TIME", Level.USER, "Неверное время",
        "Время записано неверно", "пишите как 5:45, 5.45 или одним числом.",
        user_text="Время пишите как 5:45, 5.45 или {plain}",
    ),
    ErrorSpec(
        "INPUT-DATE", Level.USER, "Неверная дата",
        "Дата записана неверно", "пишите как 20.10 или 20.10.2026.",
        user_text="Дату пишите как 20.10 или 20.10.2026",
    ),
    ErrorSpec(
        "INPUT-FUTURE", Level.USER, "Будущая дата",
        "Попытка записи в будущую дату", "выберите сегодняшний или прошедший день.",
        user_text="Нельзя записать на {day} — это будущее. Сегодня {today}",
    ),
    ErrorSpec(
        "INPUT-KBJU", Level.USER, "КБЖУ записаны не четырьмя числами",
        "Ручные КБЖУ записаны неверно", "напишите 4 числа через пробел, например 2800 160 80 360.",
        user_text="Напишите 4 числа через пробел: ккал, белки, жиры, углеводы. Пример: 2800 160 80 360",
    ),
    ErrorSpec(
        "INPUT-TEXT", Level.USER, "Текст неподходящей длины",
        "Текст вне допустимой длины", "напишите короче или длиннее — границы в сообщении.",
        user_text="{field} — от {low} до {high} символов. Сейчас {length}",
    ),
    ErrorSpec(
        "CITY-NOT-FOUND", Level.USER, "Город не найден",
        "Поиск города ничего не нашёл", "проверьте написание или выберите похожий город кнопкой.",
        user_text="Не нашёл город „{value}“. {maybe}Или напишите иначе",
    ),
    ErrorSpec(
        "CITY-SERVICE", Level.USER, "Сервис поиска городов не отвечает",
        "Open-Meteo Geocoding не ответил", "выберите город кнопкой или пропустите — его можно указать позже.",
        user_text=(
            "Поиск городов сейчас не отвечает. Выберите кнопкой или пропустите — "
            "город можно указать позже в настройках"
        ),
    ),
    ErrorSpec(
        "UI-STALE", Level.USER, "Устаревшее меню",
        "Нажата кнопка сброшенного или законченного ввода", "начните заново из главного меню.",
        user_text="Это меню устарело. Вот главное меню 👇",
    ),
    ErrorSpec(
        "INTERNAL", Level.USER, "Внутренняя ошибка в обработчике",
        "⚠️ {incident} · «{where}», пользователь #{user} · {detail} · {count} раз за час. Данные не изменены.",
        "передайте код Claude для исправления.",
        user_text=(
            "Что-то пошло не так, ничего не сохранено. Попробуйте ещё раз. "
            "Если повторится — код ошибки {incident}, администратор его уже получил"
        ),
    ),
    # --- Администратору (раздел 7.4.2) ---
    ErrorSpec(
        "DB-MIGRATION", Level.ADMIN, "Схема базы не совпадает с версией кода",
        "🗄 Схема базы на ревизии {current}, а код ждёт {head}.",
        "запустите «Выкладку» ещё раз — она применяет миграции; если повторяется — «Откат».",
    ),
    ErrorSpec(
        "TG-NET", Level.ADMIN, "Сервер не может достучаться до Telegram",
        "📡 Сервер не может достучаться до api.telegram.org — вероятно, блокировка у хостера.",
        "запустите «Бот жив?» вручную. Если повторяется — смените локацию VPS (раздел 7.1) "
        "или задайте прокси в секрете TELEGRAM_PROXY.",
    ),
    ErrorSpec(
        "SYS-DISK", Level.ADMIN, "Заканчивается место на диске",
        "🧱 Диск занят на {percent}%. Неиспользуемые образы уже удалены.",
        "запустите «Очистить сервер». Если не помогло — тариф с большим диском.",
    ),
    ErrorSpec(
        "SYS-MEM", Level.ADMIN, "Заканчивается память",
        "🧱 Свободно памяти {free_mb} МБ.",
        "перезапустите бота «Выкладкой»; если повторяется — тариф с 2 ГБ памяти (vm.nano).",
    ),
    ErrorSpec(
        "HEALTH-DOWN", Level.ADMIN, "Бот не прошёл проверку здоровья",
        "🛑 Бот не прошёл проверку: {failed}. Контейнер перезапущен{restart_result}.",
        "если сообщение повторяется — запустите «Откат» на предыдущую версию.",
    ),
    ErrorSpec(
        "SSH-DOWN", Level.ADMIN, "Сервер не отвечает по SSH",
        "🔌 Сервер не отвечает по SSH, проверить бота не удалось.",
        "проверьте в панели HOSTKEY, что сервер включён и оплачен.",
    ),
    ErrorSpec(
        "BKP-FAIL", Level.ADMIN, "Бэкап не создан",
        "💾 Бэкап не создан: {detail}.",
        "запустите «Очистить сервер» в Actions и повторите. Выкладка без бэкапа не продолжается.",
    ),
    # --- Сценарии GitHub Actions (раздел 7.4.4) ---
    ErrorSpec(
        "DEPLOY-TESTS", Level.ADMIN, "Проверка на main не прошла",
        "❌ Тесты на main не прошли, выкладка отменена.",
        "подробности в сводке запуска: {url}",
    ),
    ErrorSpec(
        "DEPLOY-CONFIG", Level.ADMIN, "Выкладка остановлена из-за ошибок в настройках",
        "❌ Выкладка {version} остановлена: настройки с ошибками. Бот работает на прежней версии.",
        "исправьте секреты по списку в отчёте «Выкладки»: {url}",
    ),
    ErrorSpec(
        "DEPLOY-FAIL", Level.ADMIN, "Выкладка не удалась",
        "❌ Выкладка {version} не удалась на шаге «{step}». {rollback}",
        "подробности: {url}",
    ),
    ErrorSpec(
        "ROLLBACK-FAIL", Level.ADMIN, "Откат не удался",
        "❌ Откат на {version} не удался на шаге «{step}». {state}",
        "подробности: {url}",
    ),
    ErrorSpec(
        "SECRET-MISSING", Level.REPORT, "Не задан секрет репозитория",
        "Не задан секрет {name}.",
        "Settings → Secrets and variables → Actions → New repository secret.",
    ),
    ErrorSpec(
        "SSH-ROOT", Level.REPORT, "Не удалось войти на сервер по паролю root",
        "Не удалось войти по паролю root.",
        "проверьте SERVER_ROOT_PASSWORD и что сервер включён в панели хостера.",
    ),
    ErrorSpec(
        "SSH-KEY", Level.REPORT, "Вход по ключу deploy не сработал",
        "Вход по ключу не сработал — вход по паролю не отключён, чтобы вы не потеряли доступ.",
        "проверьте DEPLOY_SSH_PUBLIC_KEY (должен начинаться с ssh-ed25519) и DEPLOY_SSH_KEY.",
    ),
    ErrorSpec(
        "SERVER-TG", Level.REPORT, "С сервера недоступен Telegram",
        "api.telegram.org недоступен с этого сервера.",
        "смените локацию VPS (раздел 7.1).",
    ),
    ErrorSpec(
        "SERVER-LLM", Level.REPORT, "С сервера недоступен API модели",
        "API модели недоступен с сервера.",
        "проверьте LLM_BASE_URL.",
    ),
)

CATALOG: dict[str, ErrorSpec] = {spec.code: spec for spec in _SPECS}


def get(code: str) -> ErrorSpec:
    """Спецификация ошибки по коду; неизвестный код — ошибка программиста."""
    return CATALOG[code]


def admin_message(code: str, params: Mapping[str, object] | None = None) -> str:
    """Текст для администратора: что случилось + что сделать."""
    spec = get(code)
    params = params or {}
    return f"{_fill(spec.admin_text, params)}\nЧто сделать: {_fill(spec.hint, params)}"


def user_message(code: str, params: Mapping[str, object] | None = None) -> str:
    """Текст для пользователя; у ошибок без пользовательского текста — пустая строка."""
    return _fill(get(code).user_text, params or {})


def report_line(code: str, params: Mapping[str, object] | None = None) -> str:
    """Строка отчёта о настройке: «CFG-ADMIN: ADMIN_TG_IDS пуст — добавьте свой Telegram-ID …»."""
    spec = get(code)
    params = params or {}
    return f"{code}: {_fill(spec.admin_text, params)} — {_fill(spec.hint, params)}"


def markdown_table() -> str:
    """Таблица «Что делать при ошибке» для README."""
    lines = [
        "| Код | Кому | Что случилось | Что сделать |",
        "|---|---|---|---|",
    ]
    for spec in _SPECS:
        hint = spec.hint.replace("{url}", "ссылка на запуск").replace("{known}", "список в сообщении")
        hint = hint[0].upper() + hint[1:]
        lines.append(f"| `{spec.code}` | {spec.level.value} | {spec.summary} | {hint} |")
    return "\n".join(lines)
