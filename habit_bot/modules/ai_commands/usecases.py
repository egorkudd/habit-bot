"""Команды текстом и заполнение через ИИ (раздел 3.10, 3.12): разбор → карточка «Понял так» → подтверждение →
выполнение → «↩️ Отменить всё» (10 минут). Лимиты: 1000 символов (в заполнении — 4000), 50 разборов в сутки,
бюджет на месяц. Без aiogram."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Protocol

from sqlalchemy import delete, select

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.domain.parsing import logical_day
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor
from habit_bot.modules.ai_commands.domain.actions import MAX_FILL_TEXT, MAX_TEXT, ReplyInvalid, parse_reply
from habit_bot.modules.ai_commands.executor import Done, Executor
from habit_bot.modules.ai_commands.planner import Planner, Services
from habit_bot.modules.ai_commands.prompt import Context, build_messages
from habit_bot.modules.warmup.domain.warmup import format_value as warmup_format
from habit_bot.modules.workouts.domain.training import Filters, Kind
from habit_bot.platform.ai.budget import Budget, cost
from habit_bot.platform.ai.client import LlmClient, LlmError, LlmReply
from habit_bot.platform.ai.models import AiCommand

log = logging.getLogger(__name__)
UNDO_WINDOW = timedelta(minutes=10)
KEEP = timedelta(days=30)
CONTEXT_DAYS = 3  # сегодня, вчера, позавчера — записи для «удали коктейль», «планка во 2-й зарядке»
TEXT, FILL = "text", "fill"
PENDING, DONE, CANCELLED, UNDONE, ERROR = "pending", "done", "cancelled", "undone", "error"


class Alerter(Protocol):
    async def alert(self, code: str, *, where: str, **params: object) -> None: ...


@dataclass(frozen=True, slots=True)
class CommandView:
    public_id: str
    mode: str
    ops: tuple[dict[str, Any], ...]
    skipped: tuple[str, ...] = ()
    question: dict[str, Any] | None = None
    status: str = PENDING
    text: str = ""


@dataclass(frozen=True, slots=True)
class Executed:
    command: CommandView
    done: Done
    days: tuple[date, ...] = field(default_factory=tuple)


def _uuid(public_id: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(hex=public_id)
    except (ValueError, TypeError):
        return None


def summary(ops: Iterable[dict[str, Any]]) -> str:
    """Прошлое понимание для «✏️ Исправить» — строками карточки."""
    return "; ".join(op["line"] for op in ops)


class TextCommands:
    WHERE = "Команды текстом"

    def __init__(self, *, uow: UowFactory, clock: Clock, tz: tzinfo, client: LlmClient | None, budget: Budget,
                 services: Services, alerter: Alerter | None = None) -> None:
        self._uow = uow
        self._clock = clock
        self._tz = tz
        self.client = client
        self.budget = budget
        self.services = services
        self._alerter = alerter
        self._executor = Executor(services)

    @property
    def available(self) -> bool:
        return self.client is not None

    def today(self) -> date:
        return logical_day(self._clock.now(), self._tz)

    async def _alert(self, code: str, **params: object) -> None:
        if self._alerter is not None:
            await self._alerter.alert(code, where=self.WHERE, **params)

    # --- контекст для модели: без имени, ID и профиля ---
    async def context(self, actor: Actor, today: date) -> Context:
        s = self.services
        now = self._clock.now().astimezone(self._tz)
        foods = [i.name for i in await s.food.items(actor)] if s.food else []
        habits = [h.name for h in await s.habits.habits(actor)] if s.habits else []
        warmup = [t.short for t in await s.warmup.templates(actor)] if s.warmup else []
        exercises: list[str] = []
        if s.workouts is not None:
            exercises = [e.name for e in await s.workouts.exercises(actor, Filters(kind=Kind.FREE, show_all=True))]
        days: dict[str, dict[str, Any]] = {}
        for back in range(CONTEXT_DAYS):
            day = today - timedelta(days=back)
            info: dict[str, Any] = {}
            if s.food is not None:
                info["food"] = [{"item": e.name, "quantity": float(e.quantity),
                                 "time": e.logged_at.astimezone(self._tz).strftime("%H:%M") if e.logged_at else ""}
                                for e in await s.food.entries(actor, day)]
            if s.warmup is not None:
                info["warmup"] = [{"number": w.number, "values": {i.name: warmup_format(i.measure, i.value)
                                                                  for i in w.items}}
                                  for w in await s.warmup.sessions(actor, day)]
            days[day.isoformat()] = {k: v for k, v in info.items() if v}
        return Context(today=today.isoformat(), now=now.strftime("%Y-%m-%d %H:%M"), foods=foods, habits=habits,
                       warmup=warmup, exercises=exercises, days={k: v for k, v in days.items() if v})

    # --- разбор ---
    async def _ask(self, messages: list[dict[str, str]]) -> tuple[Any, LlmReply, LlmReply | None]:
        assert self.client is not None
        first = await self.client.complete(messages)
        try:
            return parse_reply(first.text), first, None
        except ReplyInvalid:
            log.warning("Ответ модели не по схеме — повтор", extra={"code": "LLM-UNAVAILABLE"})
        second = await self.client.complete(messages)  # раздел 7.2: один повтор, затем «попробуйте кнопками»
        try:
            return parse_reply(second.text), first, second
        except ReplyInvalid as exc:
            raise _Invalid(first, second) from exc

    async def parse(self, actor: Actor, text: str, *, mode: str = TEXT, previous: str | None = None) -> CommandView:
        clean = text.strip()
        limit = MAX_FILL_TEXT if mode == FILL else MAX_TEXT
        if len(clean) > limit:
            raise AppError("LLM-TOO-LONG", limit=limit)
        if self.client is None:
            raise AppError("LLM-OFF")
        now = self._clock.now()
        usage = await self.budget.usage(now)
        if usage.exhausted:
            await self._alert("LLM-BUDGET", budget=usage.budget, spent=usage.spent)
            raise AppError("LLM-BUDGET")
        today = self.today()
        if await self.budget.used_today(actor.user_id, today) >= self.budget.daily_limit:
            raise AppError("LLM-USER-LIMIT", limit=self.budget.daily_limit)
        messages = build_messages(await self.context(actor, today), clean, previous=previous)
        record = AiCommand(user_id=actor.user_id, day=today, mode=mode, text=clean[:MAX_FILL_TEXT], actions={},
                           undo=[], status=ERROR, tokens_in=0, tokens_out=0, cost_usd=0.0)
        try:
            parsed, first, second = await self._ask(messages)
        except LlmError as err:
            await self._save(record)
            await self._alert(err.code, detail=err.detail)
            raise AppError("LLM-BUDGET" if err.code == "LLM-402" else "LLM-UNAVAILABLE") from err
        except _Invalid as invalid:
            self._account(record, invalid.first, invalid.second)
            await self._save(record)
            raise AppError("LLM-UNAVAILABLE") from invalid
        self._account(record, first, second)
        plan = await Planner(self.services, actor, today, self._tz).plan(parsed.actions)
        question = parsed.question.model_dump() if parsed.question and not plan.ops else None
        record.actions = {"ops": plan.ops, "skipped": plan.skipped, "question": question}
        record.status = PENDING if plan.ops or question else ERROR
        await self._save(record)
        after = await self.budget.usage(now)
        if after.warning and not usage.warning:
            await self._alert("LLM-BUDGET-80", budget=after.budget, spent=after.spent)
        if record.status == ERROR:
            if plan.skipped:
                return self._view(record)
            raise AppError("LLM-UNCLEAR")
        return self._view(record)

    @staticmethod
    def _account(record: AiCommand, *replies: LlmReply | None) -> None:
        for reply in replies:
            if reply is not None:
                record.tokens_in += reply.prompt_tokens
                record.tokens_out += reply.completion_tokens
                record.cost_usd += float(cost(reply))

    async def _save(self, record: AiCommand) -> None:
        async with self._uow() as uow:
            uow.session.add(record)
            await uow.session.flush()

    @staticmethod
    def _view(row: AiCommand) -> CommandView:
        data = row.actions if isinstance(row.actions, dict) else {}
        return CommandView(row.public_id.hex, row.mode, tuple(data.get("ops", [])), tuple(data.get("skipped", [])),
                           data.get("question"), row.status, row.text)

    async def _own(self, session: Any, actor: Actor, public_id: str) -> AiCommand | None:
        public = _uuid(public_id)
        if public is None:
            return None
        found: AiCommand | None = (await session.execute(select(AiCommand).where(
            AiCommand.public_id == public, AiCommand.user_id == actor.user_id))).scalar_one_or_none()
        return found

    async def command(self, actor: Actor, public_id: str) -> CommandView | None:
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            return self._view(row) if row else None

    async def drop(self, actor: Actor, public_id: str, indexes: Iterable[int]) -> CommandView | None:
        """«Убрать: N» — исключить пункты (номера с 1); «Пропустить» у дубля — то же самое."""
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is None or row.status != PENDING:
                return None
            data = dict(row.actions)
            removed = set(indexes)
            data["ops"] = [op for i, op in enumerate(data.get("ops", []), 1) if i not in removed]
            row.actions = data
            if not data["ops"]:
                row.status = CANCELLED
            return self._view(row)

    async def cancel(self, actor: Actor, public_id: str) -> None:
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is not None and row.status == PENDING:
                row.status = CANCELLED

    async def execute(self, actor: Actor, public_id: str) -> Executed | None:
        """«✅ Выполнить всё». Повторное нажатие ничего не делает: команда уже выполнена."""
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is None or row.status != PENDING or not (row.actions or {}).get("ops"):
                return None
            row.status = DONE  # сразу: второе нажатие не выполнит план ещё раз
            row.done_at = self._clock.now()
            ops = list(row.actions["ops"])
        done = await self._executor.run(actor, ops)
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            assert row is not None
            row.undo = done.undo
            view = self._view(row)
        return Executed(view, done, tuple(sorted(done.days)))

    async def undo_all(self, actor: Actor, public_id: str) -> int | None:
        """«↩️ Отменить всё» — 10 минут после выполнения. ``None`` — поздно или уже отменено."""
        async with self._uow() as uow:
            row = await self._own(uow.session, actor, public_id)
            if row is None or row.status != DONE or row.done_at is None:
                return None
            if self._clock.now() - row.done_at > UNDO_WINDOW:
                return None
            row.status = UNDONE
            records = list(row.undo)
        return await self._executor.undo(actor, records)

    async def purge(self, now: datetime | None = None) -> int:
        """Разборы хранятся 30 дней (раздел 5)."""
        moment = now or self._clock.now()
        async with self._uow() as uow:
            result = await uow.session.execute(delete(AiCommand).where(AiCommand.created_at < moment - KEEP))
            return int(getattr(result, "rowcount", 0) or 0)


class _Invalid(Exception):
    def __init__(self, first: LlmReply, second: LlmReply) -> None:
        super().__init__("ответ модели не по схеме")
        self.first = first
        self.second = second
