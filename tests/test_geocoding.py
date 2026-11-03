"""Раздел 4.12 и архитектура (правило 10): поиск городов через Open-Meteo — таймаут, ошибки, кэш 30 дней."""

import asyncio
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from habit_bot.platform.sources.geocoding import (
    CachedGeocoder,
    GeocoderUnavailable,
    OpenMeteoGeocoder,
    Place,
    parse_response,
)

KIROVSK = {"results": [
    {"name": "Кировск", "latitude": 67.6142, "longitude": 33.6717, "country_code": "RU",
     "admin1": "Мурманская область"},
]}


async def _server(handler: Any) -> TestServer:
    app = web.Application()
    app.router.add_get("/v1/search", handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    return server


async def test_open_meteo_request_and_parse(no_network: None) -> None:
    """Запрос на русском, до 10 результатов; ответ превращается в места с регионом и координатами."""
    seen: dict[str, str] = {}

    async def handler(request: web.Request) -> web.Response:
        seen.update(request.query)
        return web.json_response(KIROVSK)

    server = await _server(handler)
    try:
        places = await OpenMeteoGeocoder(str(server.make_url("/v1/search"))).search("Кировск")
    finally:
        await server.close()
    assert seen == {"name": "Кировск", "count": "10", "language": "ru", "format": "json"}
    assert places == [Place("Кировск", "Мурманская область", "RU", 67.6142, 33.6717)]


@pytest.mark.parametrize("mode", ["error", "slow", "garbage"])
async def test_open_meteo_unavailable(no_network: None, mode: str) -> None:
    """Ошибка сервиса, таймаут или не-JSON — «сервис не отвечает» (CITY-SERVICE), бот работает дальше."""

    async def handler(request: web.Request) -> web.Response:
        if mode == "slow":
            await asyncio.sleep(1)
        if mode == "error":
            return web.Response(status=500)
        return web.Response(text="не json", content_type="text/html")

    server = await _server(handler)
    try:
        with pytest.raises(GeocoderUnavailable):
            await OpenMeteoGeocoder(str(server.make_url("/v1/search")), timeout=0.2).search("Кировск")
    finally:
        await server.close()


def test_parse_empty_answer() -> None:
    """Ответ без results — ничего не найдено."""
    assert parse_response({"generationtime_ms": 0.4}) == []
    assert parse_response({"results": None}) == []


class CountingGeocoder:
    def __init__(self) -> None:
        self.calls = 0

    async def search(self, name: str) -> list[Place]:
        self.calls += 1
        return [Place(name, "Регион", "RU", 1.0, 2.0)]


async def test_cache_30_days(app: Any, clock: Any) -> None:
    """Один и тот же запрос уходит в сервис не чаще раза в 30 дней."""
    inner = CountingGeocoder()
    cached = CachedGeocoder(inner, uow=app.ctx.uow, clock=clock)
    first = await cached.search("Тула")
    assert await cached.search(" тула ") == first
    assert inner.calls == 1
    clock.advance(days=31)
    await cached.search("Тула")
    assert inner.calls == 2
