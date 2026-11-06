"""Шифрование бэкапа паролем BACKUP_PASSWORD (раздел 7): scrypt + AES-256-GCM, внутри — сжатая копия базы.

Файл в Telegram без пароля бесполезен; расшифровать: ``python -m habit_bot.ops decrypt <файл> <куда>``
(пароль берётся из переменной BACKUP_PASSWORD)."""

from __future__ import annotations

import os
import zlib

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"HBKP1\n"
SALT, NONCE = 16, 12


class WrongPassword(ValueError):
    """Пароль не подходит или файл повреждён."""


def _key(password: str, salt: bytes) -> bytes:
    return bytes(Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(password.encode("utf-8")))


def encrypt(data: bytes, password: str) -> bytes:
    salt, nonce = os.urandom(SALT), os.urandom(NONCE)
    sealed = bytes(AESGCM(_key(password, salt)).encrypt(nonce, zlib.compress(data, 6), MAGIC))
    return MAGIC + salt + nonce + sealed


def decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + SALT + NONCE + 16:
        raise WrongPassword("это не файл бэкапа habit-bot")
    start = len(MAGIC)
    salt, nonce = blob[start:start + SALT], blob[start + SALT:start + SALT + NONCE]
    try:
        packed = AESGCM(_key(password, salt)).decrypt(nonce, blob[start + SALT + NONCE:], MAGIC)
    except InvalidTag as exc:
        raise WrongPassword("пароль не подходит или файл повреждён") from exc
    return zlib.decompress(packed)
