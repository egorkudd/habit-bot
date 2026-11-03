"""Поддельный Telegram Bot API для пробного запуска в CI: ни одного реального запроса к Telegram.

``python scripts/fake_bot_api.py --port 8081`` и ``BOT_API_BASE=http://127.0.0.1:8081`` у бота.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from aiohttp import web

BOT_USER = {"id": 1000001, "is_bot": True, "first_name": "Habit Test", "username": "habit_test_bot"}


def create_app(poll_delay: float = 0.5) -> web.Application:
    app = web.Application()
    app["calls"] = []

    async def handle(request: web.Request) -> web.Response:
        method = request.match_info["method"]
        app["calls"].append(method)
        payload: dict[str, Any] = {}
        if request.can_read_body:
            payload = dict(await request.post())
        result: Any = True
        if method == "getMe":
            result = BOT_USER
        elif method == "getUpdates":
            await asyncio.sleep(poll_delay)
            result = []
        elif method == "sendMessage":
            result = {
                "message_id": len(app["calls"]),
                "date": int(time.time()),
                "chat": {"id": int(payload.get("chat_id", 0)), "type": "private"},
                "text": payload.get("text", ""),
            }
        return web.json_response({"ok": True, "result": result})

    app.router.add_route("*", "/bot{token}/{method}", handle)
    return app


def main(argv: list[str] | None = None) -> None:  # pragma: no cover — запускается в CI как процесс
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8081)
    args = parser.parse_args(argv)
    web.run_app(create_app(), host="127.0.0.1", port=args.port, print=None)


if __name__ == "__main__":  # pragma: no cover
    main()
