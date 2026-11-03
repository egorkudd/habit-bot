"""Раздел 7, «Повторы запросов»: повтор с тем же ключом не создаёт дубль и возвращает прежний результат."""

from datetime import timedelta
from typing import Any

from habit_bot.kernel.idempotency import IdempotencyKey, IdempotencyStore
from habit_bot.modules.users.usecases import SignInTelegram
from tests.conftest import ADMIN_ID


async def test_same_request_runs_once(app: Any, clock: Any) -> None:
    """Повтор того же запроса (например, повторно доставленный апдейт) выполняется один раз."""
    sign_in: SignInTelegram = app.ctx.services["users.sign_in"]
    actor = await sign_in.execute(ADMIN_ID, "Егор")
    assert actor is not None
    store = IdempotencyStore()
    calls: list[int] = []

    async def action() -> dict[str, Any]:
        calls.append(1)
        return {"entry": len(calls)}

    for _ in range(2):
        async with app.ctx.uow() as uow:
            result = await store.run_once(uow.session, user_id=actor.user_id, request_id="tg:1",
                                          now=clock.now(), action=action)
            assert result == {"entry": 1}
    assert calls == [1]

    clock.advance(hours=25)
    async with app.ctx.uow() as uow:
        result = await store.run_once(uow.session, user_id=actor.user_id, request_id="tg:1",
                                      now=clock.now(), action=action)
    assert result == {"entry": 2}

    async with app.ctx.uow() as uow:
        uow.session.add(IdempotencyKey(user_id=actor.user_id, request_id="old", result={},
                                       created_at=clock.now() - timedelta(days=2)))
    async with app.ctx.uow() as uow:
        assert await store.purge(uow.session, clock.now()) == 1
