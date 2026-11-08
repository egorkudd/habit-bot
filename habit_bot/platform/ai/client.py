"""Клиент языковой модели (раздел 7.2): OpenAI-совместимый API, JSON-ответ, без режима рассуждения, запасной
провайдер. Адрес, модель и ключ — из ``.env`` (``LLM_*``, ``LLM_FALLBACK_*``); замена провайдера без правки кода."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import aiohttp

log = logging.getLogger(__name__)
TIMEOUT_SECONDS = 90  # длинный ответ (заполнение) идёт дольше обычного
MAX_OUTPUT_TOKENS = 8000


@dataclass(frozen=True, slots=True)
class LlmReply:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    provider: str = ""


class LlmError(Exception):
    """Код каталога ошибок: ``LLM-401`` (ключ), ``LLM-402`` (баланс), ``LLM-429`` (частота), ``LLM-DOWN``."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


class LlmClient(Protocol):
    async def complete(self, messages: Sequence[dict[str, str]]) -> LlmReply: ...


def status_code(status: int) -> str:
    if status == 401:
        return "LLM-401"
    if status == 402:
        return "LLM-402"
    if status == 429:
        return "LLM-429"
    return "LLM-DOWN"


def parse_completion(payload: dict[str, Any], provider: str) -> LlmReply:
    """Ответ ``/chat/completions``: текст и учёт токенов (кэш — ``prompt_cache_hit_tokens`` у DeepSeek)."""
    try:
        text = str(payload["choices"][0]["message"]["content"] or "")
    except (KeyError, IndexError, TypeError) as exc:
        raise LlmError("LLM-DOWN", "ответ без choices") from exc
    usage = payload.get("usage") or {}
    cached = usage.get("prompt_cache_hit_tokens") or (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    return LlmReply(text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0),
                    int(cached or 0), provider)


class OpenAiCompatibleClient:
    """POST ``{base}/chat/completions`` с ``response_format: json_object`` и ``temperature: 0``."""

    def __init__(self, *, base_url: str, model: str, api_key: str, timeout: float = TIMEOUT_SECONDS) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._key = api_key
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self.provider = base_url

    async def complete(self, messages: Sequence[dict[str, str]]) -> LlmReply:
        # max_tokens — с запасом под длинный список действий в заполнении (DeepSeek и Kimi принимают 8000)
        body = {"model": self._model, "messages": list(messages), "temperature": 0, "max_tokens": MAX_OUTPUT_TOKENS,
                "response_format": {"type": "json_object"}, "stream": False}
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"}
        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session, \
                    session.post(self._url, json=body, headers=headers) as response:
                if response.status != 200:
                    raise LlmError(status_code(response.status), f"HTTP {response.status}")
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise LlmError("LLM-DOWN", type(exc).__name__) from exc
        return parse_completion(payload if isinstance(payload, dict) else {}, self.provider)


class FallbackClient:
    """Основной провайдер, при ошибке — запасной (раздел 7.2). Ошибка ключа или баланса основного тоже
    переключает: разбор продолжает работать, администратор получает оповещение."""

    def __init__(self, primary: LlmClient, fallback: LlmClient) -> None:
        self._primary = primary
        self._fallback = fallback
        self.last_error: LlmError | None = None

    async def complete(self, messages: Sequence[dict[str, str]]) -> LlmReply:
        try:
            reply = await self._primary.complete(messages)
            self.last_error = None
            return reply
        except LlmError as err:
            self.last_error = err
            log.warning("Основной провайдер ИИ недоступен (%s), пробую запасной", err.code, extra={"code": err.code})
            return await self._fallback.complete(messages)


def build_client(*, base_url: str | None, model: str | None, api_key: str | None,
                 fallback: tuple[str | None, str | None, str | None] = (None, None, None)) -> LlmClient | None:
    """``None`` — модель не настроена: разбор текстом выключен, кнопки работают."""
    if not (base_url and model and api_key):
        return None
    primary = OpenAiCompatibleClient(base_url=base_url, model=model, api_key=api_key)
    f_url, f_model, f_key = fallback
    if f_url and f_model and f_key:
        return FallbackClient(primary, OpenAiCompatibleClient(base_url=f_url, model=f_model, api_key=f_key))
    return primary
