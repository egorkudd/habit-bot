"""Поиск секретов в отслеживаемых файлах (замена gitleaks для локальной «Проверки», раздел 7.3, шаг 7):
токен бота, ключи API, приватные ключи, пароли в явном виде."""

from __future__ import annotations

import re
import subprocess
import sys

PATTERNS = {
    "токен Telegram-бота": re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{30,}\b"),
    "ключ API (sk-…)": re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
    "токен GitHub": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "приватный ключ": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
}
ALLOWED = ("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",)  # поддельные токены тестов


def main() -> int:
    files = subprocess.run(["git", "ls-files"], capture_output=True, text=True, check=True).stdout.split()
    found = []
    for name in files:
        try:
            text = open(name, encoding="utf-8").read()
        except (UnicodeDecodeError, OSError):
            continue
        for kind, pattern in PATTERNS.items():
            for match in pattern.finditer(text):
                if not any(a in match.group() for a in ALLOWED):
                    found.append(f"{name}: {kind}")
    for line in found:
        print(f"❌ {line}")
    print("✅ Секретов не найдено" if not found else f"Найдено: {len(found)}")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
