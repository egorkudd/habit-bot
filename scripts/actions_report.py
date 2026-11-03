"""Отчёты сценариев «Выкладка», «Откат» и «Бот жив?» (раздел 7.4.4).

Разбирает вывод ``deploy/remote.sh`` (строки ``STEP …`` и последнюю ``RESULT …``), пишет сводку
для страницы запуска и текст оповещения в Telegram. Тексты ошибок — из каталога (раздел 7.4).

    python scripts/actions_report.py deploy --log deploy.log --version 0.1.0 --url URL
    python scripts/actions_report.py rollback --log rollback.log --url URL
    python scripts/actions_report.py health --log health.log
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from habit_bot.kernel.errors.catalog import admin_message  # noqa: E402


@dataclass
class RemoteRun:
    steps: list[str] = field(default_factory=list)
    status: str = ""
    fields: dict[str, str] = field(default_factory=dict)
    config_problems: list[str] = field(default_factory=list)


def parse_log(text: str) -> RemoteRun:
    run = RemoteRun()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("STEP "):
            run.steps.append(line[5:])
        elif line.startswith("RESULT "):
            parts = line[7:].split()
            run.status = parts[0] if parts and "=" not in parts[0] else ""
            run.fields = dict(p.split("=", 1) for p in parts if "=" in p)
        elif line[:1].isdigit() and ". CFG-" in line:
            run.config_problems.append(line)
    return run


def _human(value: str) -> str:
    return value.replace("_", " ")


def _steps_table(run: RemoteRun, failed_step: str | None) -> list[str]:
    lines = ["| Шаг | Результат |", "|---|---|"]
    for step in run.steps:
        mark = "❌" if step == failed_step else ("↩️" if step in {"Откат", "Возврат"} else "✅")
        lines.append(f"| {step} | {mark} |")
    return lines


def deploy_report(run: RemoteRun, *, version: str, url: str, kind: str) -> tuple[str, str]:
    """Возвращает (сводка markdown, текст оповещения)."""
    title = "Выкладка" if kind == "deploy" else "Откат"
    version = run.fields.get("version", version) or "?"
    if run.status == "ok":
        message = f"✅ Версия {version} выложена" if kind == "deploy" else f"✅ Откат на версию {version} выполнен"
        summary = [f"### {title} {version}: готово ✅", "", *_steps_table(run, None)]
        return "\n".join(summary), message

    step = _human(run.fields.get("step", "")) or (run.steps[-1] if run.steps else "Подключение к серверу")
    code = run.fields.get("code") or ("DEPLOY-FAIL" if kind == "deploy" else "ROLLBACK-FAIL")
    params: dict[str, object] = {"version": version, "step": step, "url": url}
    if code == "DEPLOY-FAIL":
        rolled = run.fields.get("rolled_back", "none")
        params["rollback"] = (
            f"Вернул {rolled}, данные целы." if rolled not in {"", "none"}
            else "Предыдущей рабочей версии нет — бот остановлен, данные целы."
        )
    elif code == "ROLLBACK-FAIL":
        params["state"] = _human(run.fields.get("state", "")) or "Бот работает на прежней версии."
    elif code == "BKP-FAIL":
        params["detail"] = "ошибка на шаге «Бэкап», выкладка остановлена до остановки бота"
    message = admin_message(code, params)
    summary = [f"### {title} {version}: не удалась на шаге «{step}» ❌", "", *_steps_table(run, step)]
    if run.config_problems:
        summary += ["", "**Настройки с ошибками (бот работает на прежней версии):**", ""]
        summary += [f"- {line}" for line in run.config_problems]
    summary += ["", f"Код: `{code}`. {message.splitlines()[-1]}"]
    return "\n".join(summary), message


def health_report(text: str, *, ssh_failed: bool) -> tuple[str, str]:
    """Сводка и оповещение «Бот жив?». Пустое оповещение — всё в порядке."""
    if ssh_failed:
        message = admin_message("SSH-DOWN")
        return f"### Бот жив?: сервер не отвечает по SSH ❌\n\n{message}", message
    run = parse_log(text)
    if run.status == "skip":
        return f"### Бот жив?: пропущено — {_human(run.fields.get('reason', ''))}", ""
    f = run.fields
    messages: list[str] = []
    rows = ["| Проверка | Результат |", "|---|---|"]
    if f.get("ok") == "1":
        rows.append("| Бот | ✅ отвечает |")
    else:
        failed = [x for x in f.get("failed", "").split(",") if x and x != "-"]
        restarted_ok = f.get("restart_ok") == "1"
        rows.append(f"| Бот | ❌ не прошёл: {', '.join(failed) or 'нет данных'} |")
        rows.append(f"| Перезапуск | {'✅ помог' if restarted_ok else '❌ не помог'} |")
        if f.get("tg") == "0":
            messages.append(admin_message("TG-NET"))
        else:
            messages.append(admin_message("HEALTH-DOWN", {
                "failed": ", ".join(failed) or "контейнер не отвечает",
                "restart_result": ", после перезапуска бот здоров" if restarted_ok else ", но это не помогло",
            }))
    disk = f.get("host_disk") or f.get("disk") or "-"
    if disk.isdigit():
        rows.append(f"| Диск | {'⚠️' if int(disk) >= 80 else '✅'} занят на {disk}% |")
        if int(disk) >= 80:
            messages.append(admin_message("SYS-DISK", {"percent": disk}))
    mem = f.get("mem", "-")
    if mem.isdigit():
        rows.append(f"| Память | {'⚠️' if int(mem) < 80 else '✅'} свободно {mem} МБ |")
        if int(mem) < 80:
            messages.append(admin_message("SYS-MEM", {"free_mb": mem}))
    head = "### Бот жив?: " + ("есть проблемы ❌" if messages else "всё в порядке ✅")
    return "\n".join([head, "", *rows]), "\n\n".join(messages)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=["deploy", "rollback", "health"])
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--url", default="")
    parser.add_argument("--ssh-failed", action="store_true")
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--message-out", type=Path)
    args = parser.parse_args(argv)
    text = args.log.read_text(encoding="utf-8") if args.log.exists() else ""
    if args.kind == "health":
        summary, message = health_report(text, ssh_failed=args.ssh_failed)
    else:
        summary, message = deploy_report(parse_log(text), version=args.version, url=args.url, kind=args.kind)
    print(summary)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as fh:
            fh.write(summary + "\n\n")
    if args.message_out:
        args.message_out.write_text(message, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
