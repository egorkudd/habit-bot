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


def test_split_text_parts() -> None:
    """Правки 1.0.3: длинный текст заполнения — частями по строкам; строка длиннее части — по словам; пустые строки
    не дают пустых частей; каждая часть не длиннее предела."""
    from habit_bot.modules.ai_commands.domain.actions import split_text

    text = "\n".join(["а" * 40, "б" * 40, "", "в " * 60])
    parts = split_text(text, 50)
    assert parts[0] == "а" * 40 and parts[1].startswith("б" * 40)
    assert all(0 < len(p) <= 50 for p in parts) and "".join(parts).count("в") == 60
    assert split_text("x" * 120, 50) == ["x" * 50, "x" * 50, "x" * 20]
    assert split_text("коротко", 50) == ["коротко"]


def test_split_text_long_line_after_short_and_empty() -> None:
    """Короткая строка, потом строка длиннее части — короткая уходит отдельной частью; пустой текст — без частей."""
    from habit_bot.modules.ai_commands.domain.actions import split_text

    assert split_text("abc\n" + "x" * 60, 50) == ["abc", "x" * 50, "x" * 10]
    assert split_text("\n\n", 50) == []
