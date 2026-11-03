"""Шина событий: подписчики узнают об изменениях только после успешного commit."""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

log = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class DomainEvent:
    user_id: int
    occurred_at: datetime


Handler = Callable[[DomainEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[DomainEvent], list[Handler]] = defaultdict(list)

    def subscribe(self, event_type: type[DomainEvent], handler: Handler) -> None:
        self._handlers[event_type].append(handler)

    async def publish(self, event: DomainEvent) -> None:
        """Ошибка одного подписчика не мешает остальным и не откатывает уже сохранённые данные."""
        for handler in self._handlers.get(type(event), []):
            try:
                await handler(event)
            except Exception:
                log.exception("Подписчик %s упал на %s", handler, type(event).__name__)
