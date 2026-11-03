#!/usr/bin/env bash
# «Настроить сервер» (раздел 7.3). Выполняется от root (или deploy через sudo), можно запускать повторно.
# Вход: переменная DEPLOY_PUB — публичный ключ выкладки.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

say() { echo "▶ $*"; }

: "${DEPLOY_PUB:?нужен публичный ключ выкладки}"
case "$DEPLOY_PUB" in
  ssh-ed25519\ *|ssh-rsa\ *|ecdsa-*) ;;
  *) echo "DEPLOY_SSH_PUBLIC_KEY не похож на публичный ключ (ожидается ssh-ed25519 …)" >&2; exit 2 ;;
esac

say "Обновление системы"
apt-get update -q
apt-get -y -q -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold upgrade
apt-get install -y -q --no-install-recommends \
  ca-certificates curl ufw unattended-upgrades docker.io docker-compose-v2 python3

say "Автоматические обновления безопасности"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
CONF

say "Файрвол: открыт только SSH"
ufw allow OpenSSH >/dev/null
ufw --force enable >/dev/null
ufw status | head -5

say "Подкачка 1 ГБ"
if ! swapon --show=NAME --noheadings | grep -qx /swapfile; then
  if [ ! -f /swapfile ]; then
    fallocate -l 1G /swapfile
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
  fi
  swapon /swapfile
fi
grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab

say "Docker и ограничение размера его логов"
install -d /etc/docker
cat > /etc/docker/daemon.json <<'CONF'
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "2" }
}
CONF
systemctl enable docker >/dev/null 2>&1
systemctl restart docker

say "Пользователь deploy"
id deploy >/dev/null 2>&1 || useradd -m -s /bin/bash deploy
usermod -aG docker deploy
install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
printf '%s\n' "$DEPLOY_PUB" > /home/deploy/.ssh/authorized_keys
chown deploy:deploy /home/deploy/.ssh/authorized_keys
chmod 600 /home/deploy/.ssh/authorized_keys
# Повторный запуск «Настроить сервер» идёт по ключу deploy, поэтому нужен sudo без пароля.
echo 'deploy ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-deploy
chmod 440 /etc/sudoers.d/90-deploy
visudo -cf /etc/sudoers.d/90-deploy >/dev/null

say "Каталоги бота"
install -d -o deploy -g deploy /srv/bot /srv/bot/app /srv/bot/data
install -d -o deploy -g deploy /srv/bot/data/backup /srv/bot/data/logs /srv/bot/data/tmp

say "Готово: $(lsb_release -ds 2>/dev/null || echo Linux), $(docker --version), $(docker compose version --short)"
