#!/usr/bin/env bash
# Отключает вход по паролю и под root. Запускается только после того, как вход по ключу deploy проверен.
set -euo pipefail

# Файл с префиксом 00- читается раньше настроек облачного образа (50-cloud-init.conf) и побеждает их.
cat > /etc/ssh/sshd_config.d/00-habit-bot.conf <<'CONF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
CONF
sshd -t
systemctl reload ssh 2>/dev/null || systemctl reload sshd
echo "▶ Вход по паролю и под root отключён"
