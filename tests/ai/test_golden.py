"""Раздел 9: на наборе из 30 эталонных фраз разбор верен не меньше чем в 27. Здесь — на записанных ответах модели:
проверяется, что бот из ответа строит ровно ту карточку «Понял так», какую ждёт пользователь."""

from typing import Any

import pytest

from habit_bot.app import build_app
from habit_bot.kernel.errors import AppError
from tests.ai.golden import GOLDEN
from tests.ai.owner_data import fill
from tests.conftest import register_active
from tests.fakes import FakeLlm


def shown(view: Any) -> list[str]:
    """Что увидит пользователь — построчно."""
    if view.question and not view.ops:
        options = " ".join(f"[{o}]" for o in view.question["options"])
        return [f"? {view.question['text']} {options}"]
    return [op["line"] for op in view.ops] + [f"× {s}" for s in view.skipped]


async def understood(commands: Any, actor: Any, phrase: str) -> list[str]:
    try:
        return shown(await commands.parse(actor, phrase))
    except AppError as err:
        return [err.code]


@pytest.fixture
async def golden_app(settings: Any, fake_session: Any, clock: Any) -> Any:
    llm = FakeLlm({case["phrase"]: case["reply"] for case in GOLDEN})
    app = build_app(settings, telegram_session=fake_session, clock=clock, llm=llm)
    await app.startup()
    actor = await register_active(app)
    await fill(app, actor, clock)
    yield app, actor
    await app.close()


def test_thirty_phrases() -> None:
    assert len(GOLDEN) == 30 and len({c["phrase"] for c in GOLDEN}) == 30


async def test_golden_phrases(golden_app: Any) -> None:
    app, actor = golden_app
    commands = app.ctx.services["ai_commands"]
    wrong = []
    for case in GOLDEN:
        got = await understood(commands, actor, case["phrase"])
        if got != case["expect"]:
            wrong.append((case["phrase"], got, case["expect"]))
    assert wrong == []
