"""Раздел 7: файл бэкапа в Telegram зашифрован паролем BACKUP_PASSWORD; без пароля или с чужим файлом —
понятная ошибка."""

import pytest

from habit_bot.platform.backup.crypto import MAGIC, WrongPassword, decrypt, encrypt


def test_round_trip_and_wrong_input() -> None:
    data = b"SQLite format 3\x00" + bytes(range(256)) * 100
    sealed = encrypt(data, "очень-длинный-пароль")
    assert sealed.startswith(MAGIC) and data[:16] not in sealed and len(sealed) < len(data)  # сжато
    assert decrypt(sealed, "очень-длинный-пароль") == data
    assert encrypt(data, "очень-длинный-пароль") != sealed  # новая соль и nonce каждый раз
    for blob, password in ((sealed, "другой-пароль-123"), (b"not a backup", "x"), (MAGIC + b"short", "x"),
                           (sealed[:-1] + bytes([sealed[-1] ^ 1]), "очень-длинный-пароль")):
        with pytest.raises(WrongPassword):
            decrypt(blob, password)
