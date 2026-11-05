"""Раздел 7.2: клиент языковой модели (OpenAI-совместимый, запасной провайдер), учёт стоимости и бюджета."""

from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from habit_bot.platform.ai.budget import Usage, cost
from habit_bot.platform.ai.client import (
    FallbackClient,
    LlmError,
    LlmReply,
    OpenAiCompatibleClient,
    build_client,
    parse_completion,
    status_code,
)

COMPLETION = {"choices": [{"message": {"content": '{"actions": []}'}}],
              "usage": {"prompt_tokens": 1200, "completion_tokens": 80, "prompt_cache_hit_tokens": 1000}}


async def _server(handler: Any) -> TestServer:
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    return server


async def test_request_body_and_reply(no_network: None) -> None:
    """Запрос: модель, JSON-ответ, температура 0, ключ в заголовке; ответ — текст и токены с кэшем."""
    seen: dict[str, Any] = {}

    async def handler(request: web.Request) -> web.Response:
        seen["body"] = await request.json()
        seen["auth"] = request.headers["Authorization"]
        return web.json_response(COMPLETION)

    server = await _server(handler)
    try:
        client = OpenAiCompatibleClient(base_url=str(server.make_url("/v1/")), model="m", api_key="k")
        reply = await client.complete([{"role": "user", "content": "привет"}])
    finally:
        await server.close()
    assert seen["auth"] == "Bearer k"
    assert seen["body"]["response_format"] == {"type": "json_object"} and seen["body"]["temperature"] == 0
    assert seen["body"]["model"] == "m" and seen["body"]["messages"][0]["content"] == "привет"
    assert (reply.text, reply.prompt_tokens, reply.completion_tokens, reply.cached_tokens) == (
        '{"actions": []}', 1200, 80, 1000)


@pytest.mark.parametrize(("status", "code"), [(401, "LLM-401"), (402, "LLM-402"), (429, "LLM-429"),
                                              (500, "LLM-DOWN")])
async def test_http_errors_become_codes(no_network: None, status: int, code: str) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=status)

    server = await _server(handler)
    try:
        client = OpenAiCompatibleClient(base_url=str(server.make_url("/v1")), model="m", api_key="k")
        with pytest.raises(LlmError) as err:
            await client.complete([])
    finally:
        await server.close()
    assert err.value.code == code
    assert status_code(status) == code


async def test_garbage_and_timeout_are_down(no_network: None) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(text="<html>не JSON</html>")

    server = await _server(handler)
    try:
        client = OpenAiCompatibleClient(base_url=str(server.make_url("/v1")), model="m", api_key="k")
        with pytest.raises(LlmError) as err:
            await client.complete([])
    finally:
        await server.close()
    assert err.value.code == "LLM-DOWN"
    dead = OpenAiCompatibleClient(base_url="http://127.0.0.1:9", model="m", api_key="k", timeout=1)
    with pytest.raises(LlmError):
        await dead.complete([])


def test_parse_completion_variants() -> None:
    openai_cache = {"choices": [{"message": {"content": None}}],
                    "usage": {"prompt_tokens": 10, "prompt_tokens_details": {"cached_tokens": 4}}}
    assert parse_completion(openai_cache, "p") == LlmReply("", 10, 0, 4, "p")
    assert parse_completion({"choices": [{"message": {"content": "x"}}]}, "p") == LlmReply("x", 0, 0, 0, "p")
    with pytest.raises(LlmError):
        parse_completion({"choices": []}, "p")


class _Stub:
    def __init__(self, reply: LlmReply | None = None) -> None:
        self.reply = reply
        self.calls = 0

    async def complete(self, messages: Sequence[dict[str, str]]) -> LlmReply:
        self.calls += 1
        if self.reply is None:
            raise LlmError("LLM-402", "баланс")
        return self.reply


async def test_fallback_provider() -> None:
    """Основной не отвечает или без баланса — разбор идёт через запасной (раздел 7.2)."""
    good = LlmReply("{}", provider="запасной")
    client = FallbackClient(_Stub(), _Stub(good))
    assert await client.complete([]) == good
    assert client.last_error is not None and client.last_error.code == "LLM-402"
    healthy = FallbackClient(_Stub(LlmReply("ok")), _Stub(good))
    assert (await healthy.complete([])).text == "ok" and healthy.last_error is None


def test_build_client() -> None:
    """Без адреса, модели или ключа — None (разбор выключен); с запасным — FallbackClient."""
    assert build_client(base_url=None, model="m", api_key="k") is None
    assert build_client(base_url="https://a", model="m", api_key=None) is None
    assert isinstance(build_client(base_url="https://a", model="m", api_key="k"), OpenAiCompatibleClient)
    assert isinstance(build_client(base_url="https://a", model="m", api_key="k",
                                   fallback=("https://b", "m2", "k2")), FallbackClient)
    assert isinstance(build_client(base_url="https://a", model="m", api_key="k",
                                   fallback=("https://b", None, "k2")), OpenAiCompatibleClient)


def test_cost_and_usage() -> None:
    """Стоимость по пиковым ценам: вход 0,30 $, кэш 0,003 $, выход 1,20 $ за 1 млн токенов."""
    assert cost(LlmReply("", 1_000_000, 1_000_000, 0)) == Decimal("1.5")
    assert cost(LlmReply("", 1200, 80, 1000)) == Decimal("0.000159")
    assert cost(LlmReply("", 10, 0, 50)) == Decimal("0.000000")
    assert Usage(Decimal(4), Decimal(5)).warning and not Usage(Decimal(4), Decimal(5)).exhausted
    assert Usage(Decimal(5), Decimal(5)).exhausted
    assert not Usage(Decimal("3.99"), Decimal(5)).warning
