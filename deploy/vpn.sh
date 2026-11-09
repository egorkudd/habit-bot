#!/usr/bin/env bash
# Личный VPN на сервере бота: Xray, VLESS + Reality на порту 443/tcp — снаружи выглядит как обычный HTTPS к сайту
# маскировки, поэтому его не режут, как WireGuard и OpenVPN. Бот не затрагивается: Xray — отдельная служба systemd,
# бот ходит в Telegram сам, входящих портов у него нет.
#
# Запуск из веб-консоли хостинга под root (SSH не нужен):
#   curl -fsSL https://raw.githubusercontent.com/egorkudd/habit-bot/main/deploy/vpn.sh | bash
#   curl -fsSL …/deploy/vpn.sh | bash -s show            — снова показать ссылки и QR-коды
#   curl -fsSL …/deploy/vpn.sh | bash -s add tablet      — добавить устройство
#   curl -fsSL …/deploy/vpn.sh | bash -s remove tablet   — отключить устройство
#   curl -fsSL …/deploy/vpn.sh | bash -s uninstall       — удалить VPN, закрыть порт
# Первый запуск создаёт 6 устройств (phone1…phone6; число — DEVICES=8 перед bash). Повторный запуск ключи не меняет.
# Ссылки — это ключи доступа: показываются только в консоли, в репозиторий, чат и логи бота не попадают.
set -euo pipefail

CMD=${1:-install}
NAME=${2:-}
DEVICES=${DEVICES:-6}
PORT=443
SNI=${SNI:-www.microsoft.com}         # сайт маскировки: TLS 1.3 и HTTP/2, открывается из России
XRAY_DIR=${XRAY_DIR:-/usr/local/etc/xray}  # другой каталог — только для теста сценария
SYSCTL_DIR=${SYSCTL_DIR:-/etc/sysctl.d}
CONF=$XRAY_DIR/config.json
STATE=$XRAY_DIR/vpn.env               # закрытый ключ сервера, shortId, сайт маскировки (chmod 600)

say() { echo "▶ $*"; }
die() { echo "✖ $*" >&2; exit 1; }
[ "$(id -u)" = 0 ] || die "Нужен root: войдите в веб-консоль под root или добавьте sudo перед bash"

valid_name() { [[ $1 =~ ^[A-Za-z0-9_-]{1,32}$ ]] || die "Имя устройства — латиница, цифры, - и _, до 32 знаков"; }

public_key() {  # открытый ключ из закрытого; вывод xray разный в версиях: «Public key:» или «Password:»
  xray x25519 -i "$1" | sed -n 's/^\(Public key\|Password[^:]*\): *//p' | head -1
}

server_ip() {
  ip -4 route get 1.1.1.1 2>/dev/null | sed -n 's/.* src \([0-9.]*\).*/\1/p'
}

show() {
  [ -f "$CONF" ] && [ -f "$STATE" ] || die "VPN ещё не установлен: запустите без параметров"
  # shellcheck disable=SC1090
  . "$STATE"
  local pbk ip
  pbk=$(public_key "$PRIVATE_KEY")
  ip=$(server_ip)
  echo
  echo "Ссылки для приложений (Android: v2rayNG или Hiddify; iPhone: Streisand или V2Box; Windows/macOS: Hiddify)."
  echo "В приложении: «+» → «Импорт из буфера» или «Сканировать QR». Одна ссылка — одно устройство."
  jq -r '.inbounds[0].settings.clients[] | "\(.id) \(.email)"' "$CONF" | while read -r id name; do
    link="vless://$id@$ip:$PORT?encryption=none&flow=xtls-rprx-vision&security=reality&sni=$SNI&fp=chrome&pbk=$pbk&sid=$SHORT_ID&type=tcp#$name"
    echo
    echo "━━ $name"
    echo "$link"
    qrencode -t ansiutf8 -m 1 "$link"
  done
}

write_config() {  # клиенты — JSON-массив из stdin
  local clients tmp
  clients=$(cat)
  tmp=$(mktemp --suffix=.json)  # xray узнаёт формат по расширению
  jq -n --argjson clients "$clients" --arg key "$PRIVATE_KEY" --arg sid "$SHORT_ID" --arg sni "$SNI" \
    --argjson port "$PORT" '{
      log: {loglevel: "warning", access: "none"},
      inbounds: [{
        listen: "0.0.0.0", port: $port, protocol: "vless",
        settings: {clients: $clients, decryption: "none"},
        streamSettings: {network: "tcp", security: "reality", realitySettings: {
          dest: ($sni + ":443"), serverNames: [$sni], privateKey: $key, shortIds: [$sid]}},
        sniffing: {enabled: true, destOverride: ["http", "tls", "quic"], routeOnly: true}}],
      outbounds: [{protocol: "freedom", tag: "direct"}, {protocol: "blackhole", tag: "block"}],
      routing: {rules: [{type: "field", ip: ["geoip:private"], outboundTag: "block"}]}
    }' > "$tmp"
  local out
  if ! out=$(xray run -test -config "$tmp" 2>&1); then
    echo "$out" | tail -5 >&2
    rm -f "$tmp"
    die "Xray не принял настройки — ничего не изменено"
  fi
  # служба Xray работает от nobody: файл читает только root и группа nobody
  install -m 640 -o root -g "$(id -gn nobody)" "$tmp" "$CONF"
  rm -f "$tmp"
  systemctl restart xray
  sleep 1
  systemctl is-active --quiet xray || die "Xray не запустился: journalctl -u xray -n 50"
}

clients() { jq -c '.inbounds[0].settings.clients' "$CONF"; }

install_vpn() {
  if [ -f "$CONF" ] && [ -f "$STATE" ]; then
    say "VPN уже установлен — ключи прежние"
    show
    return
  fi
  say "Пакеты: jq, qrencode"
  DEBIAN_FRONTEND=noninteractive apt-get update -qq </dev/null
  DEBIAN_FRONTEND=noninteractive apt-get install -y -qq jq qrencode curl openssl </dev/null >/dev/null
  say "Xray (официальный установщик XTLS)"
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ install </dev/null >/dev/null
  command -v xray >/dev/null || die "Xray не установился"

  say "Ключи сервера"
  PRIVATE_KEY=$(xray x25519 | sed -n 's/^Private[ ]\{0,1\}[Kk]ey: *//p' | head -1)
  [ -n "$PRIVATE_KEY" ] || die "Не удалось создать ключ Xray"
  SHORT_ID=$(openssl rand -hex 8)
  umask 077
  printf 'PRIVATE_KEY=%s\nSHORT_ID=%s\nSNI=%s\n' "$PRIVATE_KEY" "$SHORT_ID" "$SNI" > "$STATE"

  say "Устройства: $DEVICES"
  for i in $(seq 1 "$DEVICES"); do
    jq -n --arg id "$(xray uuid)" --arg name "phone$i" '{id: $id, email: $name, flow: "xtls-rprx-vision"}'
  done | jq -s '.' | write_config

  say "Сеть: BBR — ровнее видео на дальнем канале"
  printf 'net.core.default_qdisc=fq\nnet.ipv4.tcp_congestion_control=bbr\n' > "$SYSCTL_DIR/90-vpn-bbr.conf"
  sysctl -q --system || true

  say "Файрвол: открыть $PORT/tcp"
  ufw allow "$PORT/tcp" >/dev/null
  systemctl enable --quiet xray
  say "Готово"
  show
}

add() {
  [ -n "$NAME" ] || die "Укажите имя: bash -s add tablet"
  valid_name "$NAME"
  # shellcheck disable=SC1090
  . "$STATE"
  clients | jq -e --arg n "$NAME" 'any(.email == $n)' >/dev/null && die "Устройство $NAME уже есть"
  clients | jq --arg id "$(xray uuid)" --arg n "$NAME" '. + [{id: $id, email: $n, flow: "xtls-rprx-vision"}]' \
    | write_config
  say "Добавлено: $NAME"
  show
}

remove() {
  [ -n "$NAME" ] || die "Укажите имя: bash -s remove tablet"
  # shellcheck disable=SC1090
  . "$STATE"
  clients | jq -e --arg n "$NAME" 'any(.email == $n)' >/dev/null || die "Устройства $NAME нет"
  clients | jq --arg n "$NAME" 'map(select(.email != $n))' | write_config
  say "Отключено: $NAME — его ссылка больше не работает"
}

uninstall() {
  bash -c "$(curl -fsSL https://github.com/XTLS/Xray-install/raw/main/install-release.sh)" @ remove --purge \
    >/dev/null || true
  rm -f "$STATE" "$CONF" "$SYSCTL_DIR/90-vpn-bbr.conf"
  ufw delete allow "$PORT/tcp" >/dev/null || true
  say "VPN удалён, порт $PORT закрыт. Бот работает как прежде"
}

case "$CMD" in
  install) install_vpn ;;
  show) show ;;
  add) add ;;
  remove) remove ;;
  uninstall) uninstall ;;
  *) die "Команды: install (по умолчанию), show, add ИМЯ, remove ИМЯ, uninstall" ;;
esac
