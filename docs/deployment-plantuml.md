# Диаграмма развертывания habit-bot

По бизнес-требованиям, ред. 10 (03.11.2026), разделы 7.1–7.4. На сервере хранится только последний бэкап.
Страница со схемами: https://claude.ai/artifact/AAdgXmuUUzL7iJMErRz4DJ

```plantuml
@startuml habit-bot-deployment
skinparam componentStyle rectangle
title Дневник привычек — диаграмма развертывания (MVP)

node "Смартфон пользователя" <<device>> as phone
node "Смартфон администратора" <<device>> as admin
cloud "Telegram Bot API\napi.telegram.org" as tg

node "VPS вне РФ (NL/DE/FI/KZ)\nUbuntu, 1 vCPU, 1 ГБ RAM + 1 ГБ swap\nufw: SSH :22, 443/tcp (VPN)" <<device>> as vps {
  node "Docker Engine + Compose" <<execution environment>> {
    node "habit-bot:<версия>\nPython 3.12" <<container>> as bot {
      component "aiogram 3 (FSM)" as aiogram
      component "APScheduler" as sched
      component "SQLAlchemy + Alembic" as orm
      component "matplotlib + Pillow" as img
      component "httpx" as http
      component "LLM-клиент (pydantic)" as llm
      artifact ".env (600)" as env
    }
    database "/srv/bot/data\nbot.db (SQLite WAL)\nbackup ×1, logs/ 14 дн ≤ 50 МБ" <<volume>> as vol
  }
  node "Xray (systemd, не в Docker)\nVLESS + Reality :443\nличный VPN владельца" <<service>> as xray
}

node "Устройства владельца\n6 шт., v2rayNG / Hiddify" <<device>> as vpnc
cloud "DeepSeek API\n+ запасной провайдер" as ds
cloud "Open-Meteo" as om
cloud "isdayoff.ru" as ido

cloud "GitHub" {
  artifact "habit-bot (private)" as repo
  artifact "Secrets" as secrets
  node "GitHub Actions\nci · deploy · rollback\nbootstrap · healthcheck · cleanup" <<execution environment>> as gha
}
database "ghcr.io\n3 последние версии" as ghcr
actor "Разработчик (Claude)" as dev
actor "Владелец" as owner

phone --> tg : переписка с ботом
admin --> tg : алерты, бэкапы
bot --> tg : HTTPS :443, long polling
orm --> vol : чтение / запись
llm --> ds : HTTPS, JSON, без ПДн
http --> om : таймаут 5 с, кэш 1 ч
http --> ido : таймаут 5 с, кэш 1 ч

dev --> repo : push, PR
owner --> repo : одобряет слияние
owner --> secrets : вносит секреты
repo --> gha : PR / push в main
secrets --> gha
gha --> ghcr : push образа
gha --> vps : SSH :22 (deploy), выкладка / откат
vps --> ghcr : docker pull
gha --> tg : healthcheck-алерты
vpnc --> xray : VLESS + Reality, TCP :443
@enduml
```
