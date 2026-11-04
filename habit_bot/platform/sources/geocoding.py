"""Поиск городов через Open-Meteo Geocoding API (раздел 4.12): таймаут 5 секунд, кэш 30 дней в ``SourceCache``."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

import aiohttp
from sqlalchemy import delete, select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.platform.sources.models import SourceCache

log = logging.getLogger(__name__)
OPEN_METEO_GEOCODING = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT_SECONDS = 5
ATTEMPTS = 2
CACHE_TTL = timedelta(days=30)
SOURCE = "geocoding"


@dataclass(frozen=True, slots=True)
class Place:
    name: str
    region: str
    country_code: str
    latitude: float
    longitude: float


class GeocoderUnavailable(Exception):
    """Сервис не ответил вовремя или ответил ошибкой."""


class Geocoder(Protocol):
    async def search(self, name: str) -> list[Place]: ...


def parse_response(payload: dict[str, Any]) -> list[Place]:
    """Ответ без ``results`` — ничего не найдено."""
    places = []
    for item in payload.get("results") or []:
        places.append(Place(
            name=str(item.get("name", "")),
            region=str(item.get("admin1") or ""),
            country_code=str(item.get("country_code") or ""),
            latitude=float(item["latitude"]),
            longitude=float(item["longitude"]),
        ))
    return places


class OpenMeteoGeocoder:
    """Таймаут 5 секунд и один повтор (архитектура, правило 10): сервис иногда отвечает дольше обычного."""

    def __init__(self, base_url: str = OPEN_METEO_GEOCODING, timeout: float = TIMEOUT_SECONDS,
                 attempts: int = ATTEMPTS) -> None:
        self._url = base_url
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._attempts = max(1, attempts)

    async def search(self, name: str) -> list[Place]:
        params = {"name": name, "count": "10", "language": "ru", "format": "json"}
        for attempt in range(1, self._attempts + 1):
            try:
                async with aiohttp.ClientSession(timeout=self._timeout) as session, \
                        session.get(self._url, params=params) as response:
                    response.raise_for_status()
                    payload = await response.json(content_type=None)
                return parse_response(payload if isinstance(payload, dict) else {})
            except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
                log.warning("Поиск городов не ответил (попытка %s): %s", attempt, type(exc).__name__,
                            extra={"code": "CITY-SERVICE"})
                if attempt == self._attempts:
                    raise GeocoderUnavailable from exc
        raise GeocoderUnavailable  # pragma: no cover — цикл выше всегда возвращает или бросает


class CachedGeocoder:
    """Один и тот же запрос не уходит в сервис чаще раза в 30 дней."""

    def __init__(self, inner: Geocoder, *, uow: UowFactory, clock: Clock, ttl: timedelta = CACHE_TTL) -> None:
        self._inner = inner
        self._uow = uow
        self._clock = clock
        self._ttl = ttl

    async def search(self, name: str) -> list[Place]:
        key = name.strip().lower()[:255]
        now = self._clock.now()
        async with self._uow() as uow:
            row = (await uow.session.execute(
                select(SourceCache).where(SourceCache.source == SOURCE, SourceCache.key == key)
            )).scalar_one_or_none()
            if row is not None and now - row.fetched_at < self._ttl:
                return [Place(**item) for item in row.data]
        places = await self._inner.search(name)
        async with self._uow() as uow:
            await uow.session.execute(delete(SourceCache).where(SourceCache.source == SOURCE, SourceCache.key == key))
            uow.session.add(SourceCache(source=SOURCE, key=key, data=[_as_dict(p) for p in places], fetched_at=now))
        return places


def _as_dict(place: Place) -> dict[str, Any]:
    return {"name": place.name, "region": place.region, "country_code": place.country_code,
            "latitude": place.latitude, "longitude": place.longitude}


__all__ = ["CachedGeocoder", "Geocoder", "GeocoderUnavailable", "OpenMeteoGeocoder", "Place"]
