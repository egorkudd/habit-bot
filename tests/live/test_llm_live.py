"""Настоящая языковая модель на 30 эталонных фразах (раздел 9): разбор верен не меньше чем в 27.

Запускается в задании CI «Внешние сервисы», если в GitHub Secrets заданы ``LLM_BASE_URL``, ``LLM_MODEL`` и
``LLM_API_KEY``; без ключа — пропускается (ключа у владельца пока нет). Один прогон — 30 разборов, около 0,02 $.
"""

import os
from typing import Any

import pytest

from habit_bot.app import build_app
from habit_bot.platform.ai.client import build_client
from tests.ai.golden import GOLDEN
from tests.ai.owner_data import fill
from tests.ai.test_golden import understood
from tests.conftest import register_active

KEYS = ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY")
NEEDED = 27

pytestmark = pytest.mark.skipif(not all(os.environ.get(k) for k in KEYS),
                                reason="ключа модели нет — живой прогон пропущен (LLM_* в GitHub Secrets)")


async def test_real_model_golden_phrases(settings: Any, fake_session: Any, clock: Any) -> None:
    client = build_client(base_url=os.environ["LLM_BASE_URL"], model=os.environ["LLM_MODEL"],
                          api_key=os.environ["LLM_API_KEY"])
    app = build_app(settings, telegram_session=fake_session, clock=clock, llm=client)
    await app.startup()
    try:
        actor = await register_active(app)
        await fill(app, actor, clock)
        commands = app.ctx.services["ai_commands"]
        wrong = []
        for case in GOLDEN:
            got = await understood(commands, actor, case["phrase"])
            if got != case["expect"]:
                wrong.append(f"{case['phrase']}: {got} вместо {case['expect']}")
        print("\n".join(wrong) or "все 30 фраз разобраны верно")
        assert len(GOLDEN) - len(wrong) >= NEEDED, "\n".join(wrong)
    finally:
        await app.close()
