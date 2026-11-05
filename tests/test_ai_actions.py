"""Раздел 7.2: ответ модели проверяется схемой — не JSON, не список, неверные действия и вопрос отбрасываются."""

import json

import pytest

from habit_bot.modules.ai_commands.domain.actions import MAX_ACTIONS, ReplyInvalid, parse_reply


@pytest.mark.parametrize("text", ["не json", "[]", '{"actions": {}}'])
def test_not_a_reply(text: str) -> None:
    with pytest.raises(ReplyInvalid):
        parse_reply(text)


def test_bad_parts_dropped() -> None:
    good = {"type": "day.off", "day": "2026-11-02"}
    reply = parse_reply(json.dumps({"actions": [good, {"type": "rm -rf"}, {"type": "weight.record", "kg": 5}],
                                    "question": {"text": ""}}))
    assert len(reply.actions) == 1 and reply.dropped == 2 and reply.question is None
    many = parse_reply(json.dumps({"actions": [good] * (MAX_ACTIONS + 5)}))
    assert len(many.actions) == MAX_ACTIONS
    asked = parse_reply(json.dumps({"actions": [], "question": {"text": "Какой творог?", "options": ["А", "Б"]}}))
    assert asked.question is not None and asked.question.options == ["А", "Б"]
    assert parse_reply("{}").actions == ()
