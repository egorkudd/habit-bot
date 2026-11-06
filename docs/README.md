# Документы habit-bot

Все документы проекта «Тг Бот». Обновляются после каждой части разработки (правило — в [`CLAUDE.md`](../CLAUDE.md)).
HTML открывается в браузере после скачивания (`Raw` → сохранить), PDF и `.md` GitHub показывает сразу.

| Документ | Файлы | Что внутри |
|---|---|---|
| Бизнес-требования, ред. 11 | [requirements.pdf](requirements.pdf), [requirements.html](requirements.html) | Что делает бот, план из 10 частей, критерии приёмки, эксплуатация |
| Архитектура и диаграммы классов | [architecture.md](architecture.md), [architecture.pdf](architecture.pdf), [architecture.html](architecture.html) | Модульный монолит, слои, модули, каналы (Telegram сейчас, web/mobile потом), классы |
| Диаграмма развертывания | [deployment.pdf](deployment.pdf), [deployment.html](deployment.html), [deployment-plantuml.md](deployment-plantuml.md) | Сервер, Docker, GitHub Actions, ghcr.io, Telegram, языковая модель |
| Ход разработки | [progress.md](progress.md) | Что сделано и принято по частям, решения и находки |
| Ручная проверка | [manual-testing.md](manual-testing.md) | Что проверить руками в Telegram после выкладки — только то, чего не видят автотесты |
| Поведенческие сценарии | [test-scenarios.md](test-scenarios.md) | Как ведёт себя бот в типичных и нештатных ситуациях — каталог автотестов `tests/scenarios` |
| Приёмка MVP | [acceptance-mvp.md](acceptance-mvp.md) | Каждый критерий раздела 9 и автотест, который его проверяет |

Первоисточники: артефакты claude.ai (требования, архитектура, развертывание) и документы проекта
`claude/progress.md`, `claude/architecture.md`, `claude/deployment-diagram.md`. Если версии расходятся —
верна та, что новее; после каждой части Claude приводит их к одному виду.
