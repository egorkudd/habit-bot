"""Отчёты сценариев (раздел 7.4.4) и сборка .env из секретов."""

from pathlib import Path
from typing import Any

from scripts import actions_report, write_env

URL = "https://github.com/egorkudd/habit-bot/actions/runs/1"

DEPLOY_OK = """STEP Подготовка
STEP Проверка настроек
Настройки в порядке
STEP Бэкап
STEP Остановка
STEP Миграции
STEP Запуск
STEP Проверка здоровья
RESULT ok version=0.2.0
"""

DEPLOY_MIGRATION_FAIL = """STEP Подготовка
STEP Проверка настроек
STEP Бэкап
STEP Остановка
STEP Миграции
sqlite3.OperationalError: duplicate column name: weekly_goal
STEP Откат
RESULT fail step=Миграции code=DEPLOY-FAIL rolled_back=0.1.0
"""

DEPLOY_CONFIG_FAIL = """STEP Подготовка
STEP Проверка настроек
Бот не запущен — исправьте настройки (Settings → Secrets and variables → Actions):
1. CFG-ADMIN: ADMIN_TG_IDS пуст — добавьте свой Telegram-ID в секрет ADMIN_TG_IDS (узнать: @userinfobot).
2. CFG-TOKEN: BOT_TOKEN не задан — скопируйте токен заново у @BotFather в секрет BOT_TOKEN.
RESULT fail step=Проверка_настроек code=DEPLOY-CONFIG
"""


def _deploy(log: str, kind: str = "deploy") -> tuple[str, str]:
    return actions_report.deploy_report(actions_report.parse_log(log), version="0.2.0", url=URL, kind=kind)


def test_deploy_success() -> None:
    """Раздел 9: успешная выкладка → «✅ Версия … выложена» и таблица шагов."""
    summary, message = _deploy(DEPLOY_OK)
    assert message == "✅ Версия 0.2.0 выложена"
    assert "| Проверка здоровья | ✅ |" in summary


def test_deploy_failed_migration_rolled_back() -> None:
    """Раздел 9: ошибка миграции → откат и сообщение с названием шага; вернул прежнюю версию."""
    summary, message = _deploy(DEPLOY_MIGRATION_FAIL)
    assert message.startswith("❌ Выкладка 0.2.0 не удалась на шаге «Миграции». Вернул 0.1.0, данные целы.")
    assert URL in message
    assert "| Миграции | ❌ |" in summary
    assert "| Откат | ↩️ |" in summary


def test_deploy_config_problems_listed() -> None:
    """Раздел 9: пустой ADMIN_TG_IDS и неверный BOT_TOKEN → в отчёте «Выкладки» оба пункта с подсказками."""
    summary, message = _deploy(DEPLOY_CONFIG_FAIL)
    assert message.startswith("❌ Выкладка 0.2.0 остановлена: настройки с ошибками.")
    assert "- 1. CFG-ADMIN: ADMIN_TG_IDS пуст" in summary
    assert "- 2. CFG-TOKEN: BOT_TOKEN не задан" in summary
    assert "не удалась на шаге «Проверка настроек»" in summary


def test_deploy_without_server_output() -> None:
    """Сервер не ответил — шаг «Подключение к серверу», бот остановлен не был."""
    _, message = _deploy("")
    assert "на шаге «Подключение к серверу»" in message
    _, message = _deploy("STEP Подготовка\nRESULT fail step=Запуск code=DEPLOY-FAIL rolled_back=none\n")
    assert "Предыдущей рабочей версии нет" in message
    _, message = _deploy("RESULT fail step=Подключение_к_серверу code=DEPLOY-FAIL rolled_back=not_configured\n")
    assert "на шаге «Подключение к серверу». Сервер не отвечает по ключу deploy" in message
    assert "запустите «Настроить сервер», затем «Выкладку» вручную" in message


def test_backup_and_rollback_messages() -> None:
    """Сбой бэкапа и отката — тексты из каталога."""
    _, message = _deploy("STEP Бэкап\nRESULT fail step=Бэкап code=BKP-FAIL\n")
    assert message.startswith("💾 Бэкап не создан")
    _, message = _deploy("RESULT ok version=0.1.0\n", kind="rollback")
    assert message == "✅ Откат на версию 0.1.0 выполнен"
    log = "STEP Миграции\nRESULT fail step=Миграции code=ROLLBACK-FAIL version=0.1.0 "
    _, message = _deploy(log + "state=работает_прежняя_версия_0.2.0\n", kind="rollback")
    assert message.startswith("❌ Откат на 0.1.0 не удался на шаге «Миграции». работает прежняя версия 0.2.0")
    _, message = _deploy("RESULT fail step=Выбор_версии code=ROLLBACK-FAIL\n", kind="rollback")
    assert "Бот работает на прежней версии." in message


def test_health_ok_and_skip() -> None:
    """«Бот жив?»: всё в порядке — без оповещения; до первой выкладки — пропуск."""
    summary, message = actions_report.health_report(
        "RESULT ok=1 failed=- tg=1 disk=40 mem=500 restarted=0 restart_ok=0 host_disk=40\n", ssh_failed=False)
    assert message == ""
    assert "всё в порядке" in summary
    summary, message = actions_report.health_report("RESULT skip reason=бот_ещё_не_выкладывался\n", ssh_failed=False)
    assert message == "" and "бот ещё не выкладывался" in summary


def test_health_problems() -> None:
    """Раздел 9: остановленный контейнер обнаружен, бот перезапущен, администратор знает, что не прошло."""
    _, message = actions_report.health_report(
        "RESULT ok=0 failed=container tg=1 disk=- mem=- restarted=1 restart_ok=1 host_disk=85\n", ssh_failed=False)
    assert "🛑 Бот не прошёл проверку: container. Контейнер перезапущен, после перезапуска бот здоров." in message
    assert "🧱 Диск занят на 85%" in message
    _, message = actions_report.health_report(
        "RESULT ok=0 failed=telegram tg=0 disk=30 mem=50 restarted=1 restart_ok=0 host_disk=30\n", ssh_failed=False)
    assert message.startswith("📡 Сервер не может достучаться до api.telegram.org")
    assert "🧱 Свободно памяти 50 МБ." in message
    _, message = actions_report.health_report(
        "RESULT ok=0 failed=- tg=1 restarted=1 restart_ok=0\n", ssh_failed=False)
    assert "контейнер не отвечает" in message and "но это не помогло" in message
    _, message = actions_report.health_report("", ssh_failed=True)
    assert message.startswith("🔌 Сервер не отвечает по SSH")


def test_report_cli(tmp_path: Path) -> None:
    """Сценарий пишет сводку и файл с текстом оповещения."""
    log = tmp_path / "deploy.log"
    log.write_text(DEPLOY_OK, encoding="utf-8")
    summary, out = tmp_path / "summary.md", tmp_path / "message.txt"
    assert actions_report.main(["deploy", "--log", str(log), "--version", "0.2.0", "--url", URL,
                                "--summary", str(summary), "--message-out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == "✅ Версия 0.2.0 выложена"
    assert actions_report.main(["health", "--log", str(tmp_path / "нет.log"), "--ssh-failed"]) == 0


def test_write_env(capsys: Any) -> None:
    """Секреты попадают в .env в одинарных кавычках; пустые не пишутся."""
    env = {"BOT_TOKEN": "123:abc", "ADMIN_TG_IDS": "1,2", "BACKUP_PASSWORD": "pa$$word-long", "LLM_API_KEY": " "}
    assert write_env.main(env) == 0
    text = capsys.readouterr().out
    assert "BOT_TOKEN='123:abc'" in text
    assert "BACKUP_PASSWORD='pa$$word-long'" in text
    assert "LLM_API_KEY" not in text
    assert "DATA_DIR='/data'" in text


def test_write_env_rejects_quotes(capsys: Any) -> None:
    """Секрет с одинарной кавычкой или переводом строки — понятная ошибка."""
    assert write_env.main({"BOT_TOKEN": "a'b", "BACKUP_PASSWORD": "x\ny"}) == 1
    assert "BOT_TOKEN, BACKUP_PASSWORD" in capsys.readouterr().err
