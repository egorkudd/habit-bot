"""Сценарий личного VPN ``deploy/vpn.sh``: настоящие команды сервера (apt, systemd, ufw, xray) заменены
заглушками в PATH — проверяется, что сценарий создаёт 6 устройств, не меняет ключи при повторе, добавляет и
отключает устройство, собирает правильную ссылку VLESS + Reality и открывает только 443/tcp.

Если рядом есть настоящий xray (``XRAY_BIN``), настройки проверяет он сам (``xray run -test``)."""

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "vpn.sh"
REAL_XRAY = os.environ.get("XRAY_BIN", "")
PRIVATE = "IPHmapK5eeavIM_f0nz1fot9DNYV7v2Y4VIXXlsI4XY"  # пара ключей только для теста, ни на одном сервере

STUBS = {
    "apt-get": "exit 0",
    "systemctl": 'echo "systemctl $*" >> "$LOG"',
    "ufw": 'echo "ufw $*" >> "$LOG"',
    "sysctl": "exit 0",
    "qrencode": 'echo "[QR]"',
    "ip": 'echo "1.1.1.1 via 10.0.0.1 dev eth0 src 203.0.113.5 uid 0"',
    "id": 'case "$1" in -u) echo 0 ;; -gn) id_real=$(command -p id -gn); echo "$id_real" ;; esac',
    "install": 'eval "dst=\\${$#}"; src=${@: -2:1}; cp "$src" "$dst"; chmod 640 "$dst"',
    "curl": 'echo "exit 0"',
    "openssl": 'echo 0123456789abcdef',
    "xray": """
case "$1" in
  x25519) echo "PrivateKey: IPHmapK5eeavIM_f0nz1fot9DNYV7v2Y4VIXXlsI4XY"
          echo "Password (PublicKey): MW_cziww7Ng-JzUo4HTH5gJVJcIHdxvPQev_0MABHmc"; echo "Hash32: H" ;;
  uuid) n=$(cat "$STUB/n" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "$STUB/n"
        printf '00000000-0000-4000-8000-%012d\\n' "$n" ;;
  run) if [ -n "$REAL_XRAY" ]; then exec "$REAL_XRAY" "$@"; fi; jq -e .inbounds "$4" >/dev/null ;;
esac""",
}


@pytest.fixture
def server(tmp_path: Path) -> dict[str, str]:
    stub = tmp_path / "bin"
    stub.mkdir()
    for name, body in STUBS.items():
        path = stub / name
        path.write_text(f"#!/usr/bin/env bash\n{body}\n")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "xray").mkdir()
    (tmp_path / "sysctl").mkdir()
    return {"PATH": f"{stub}:{os.environ['PATH']}", "STUB": str(stub), "LOG": str(tmp_path / "log"),
            "XRAY_DIR": str(tmp_path / "xray"), "SYSCTL_DIR": str(tmp_path / "sysctl"), "REAL_XRAY": REAL_XRAY,
            "HOME": str(tmp_path)}


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=60,
                          check=False)


def clients(env: dict[str, str]) -> list[str]:
    conf = json.loads((Path(env["XRAY_DIR"]) / "config.json").read_text())
    return [c["email"] for c in conf["inbounds"][0]["settings"]["clients"]]


pytestmark = pytest.mark.skipif(shutil.which("jq") is None, reason="нужен jq")


def test_install_six_devices_links_and_firewall(server: dict[str, str]) -> None:
    result = run(server)
    assert result.returncode == 0, result.stderr
    assert clients(server) == [f"phone{i}" for i in range(1, 7)]
    links = [line for line in result.stdout.splitlines() if line.startswith("vless://")]
    assert len(links) == 6
    assert links[0] == (
        "vless://00000000-0000-4000-8000-000000000001@203.0.113.5:443?encryption=none&flow=xtls-rprx-vision"
        "&security=reality&sni=www.microsoft.com&fp=chrome&pbk=MW_cziww7Ng-JzUo4HTH5gJVJcIHdxvPQev_0MABHmc"
        "&sid=0123456789abcdef&type=tcp#phone1")
    conf = json.loads((Path(server["XRAY_DIR"]) / "config.json").read_text())
    reality = conf["inbounds"][0]["streamSettings"]["realitySettings"]
    assert reality == {"dest": "www.microsoft.com:443", "serverNames": ["www.microsoft.com"],
                       "privateKey": PRIVATE, "shortIds": ["0123456789abcdef"]}
    assert conf["log"]["access"] == "none"  # чьи сайты — не пишется
    state = Path(server["XRAY_DIR"]) / "vpn.env"
    assert stat.S_IMODE(state.stat().st_mode) == 0o600
    log = Path(server["LOG"]).read_text()
    assert "ufw allow 443/tcp" in log and "systemctl enable" in log and "docker" not in log
    assert "bbr" in (Path(server["SYSCTL_DIR"]) / "90-vpn-bbr.conf").read_text()


def test_rerun_keeps_keys_add_remove(server: dict[str, str]) -> None:
    run(server)
    first = (Path(server["XRAY_DIR"]) / "config.json").read_text()
    again = run(server)
    assert "уже установлен" in again.stdout and (Path(server["XRAY_DIR"]) / "config.json").read_text() == first
    assert run(server, "add", "tablet").returncode == 0
    assert clients(server)[-1] == "tablet"
    assert "уже есть" in run(server, "add", "tablet").stderr
    assert "латиница" in run(server, "add", "мой телефон").stderr
    assert run(server, "remove", "phone2").returncode == 0
    assert "phone2" not in clients(server) and len(clients(server)) == 6
    assert "нет" in run(server, "remove", "phone2").stderr
    shown = run(server, "show")
    assert shown.stdout.count("vless://") == 6 and "[QR]" in shown.stdout


def test_show_before_install_and_unknown_command(server: dict[str, str]) -> None:
    assert "ещё не установлен" in run(server, "show").stderr
    assert "Команды:" in run(server, "fly").stderr


def test_uninstall_closes_port(server: dict[str, str]) -> None:
    run(server)
    assert run(server, "uninstall").returncode == 0
    assert not (Path(server["XRAY_DIR"]) / "vpn.env").exists()
    assert "ufw delete allow 443/tcp" in Path(server["LOG"]).read_text()
