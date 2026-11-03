"""Раздел 7.4.2: склейка оповещений за час и устойчивость к сбоям отправки."""

from typing import Any

from habit_bot.platform.alerts.alerter import AdminAlerter


class RecordingNotifier:
    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edited: list[tuple[int, int, str]] = []
        self.fail = fail

    async def send(self, chat_id: int, text: str) -> int | None:
        if self.fail:
            return None
        self.sent.append((chat_id, text))
        return len(self.sent)

    async def edit(self, chat_id: int, message_id: int, text: str) -> bool:
        self.edited.append((chat_id, message_id, text))
        return True


def _alerter(app: Any, clock: Any, notifier: Any, admins: list[int]) -> AdminAlerter:
    return AdminAlerter(uow=app.ctx.uow, clock=clock, notifier=notifier, admin_chat_ids=admins)


async def test_new_alert_after_hour(app: Any, clock: Any) -> None:
    """Через час то же оповещение приходит новым сообщением, а не правкой старого."""
    notifier = RecordingNotifier()
    alerter = _alerter(app, clock, notifier, [1, 2])
    await alerter.alert("TG-NET", where="healthcheck")
    clock.advance(minutes=30)
    await alerter.alert("TG-NET", where="healthcheck")
    clock.advance(minutes=61)
    await alerter.alert("TG-NET", where="healthcheck")
    assert len(notifier.sent) == 4  # 2 администратора × 2 окна
    assert len(notifier.edited) == 2


async def test_different_places_not_glued(app: Any, clock: Any) -> None:
    """Ошибки в разных местах — разные оповещения."""
    notifier = RecordingNotifier()
    alerter = _alerter(app, clock, notifier, [1])
    await alerter.alert("INTERNAL", where="a", incident="E-0001", user=1, detail="x")
    await alerter.alert("INTERNAL", where="b", incident="E-0002", user=1, detail="x")
    assert len(notifier.sent) == 2


async def test_unreachable_admin_does_not_break(app: Any, clock: Any) -> None:
    """Если администратор недоступен, оповещение сохраняется, а бот продолжает работать."""
    notifier = RecordingNotifier(fail=True)
    alerter = _alerter(app, clock, notifier, [1])
    await alerter.alert("SYS-DISK", where="health", percent=85)
    await alerter.alert("SYS-DISK", where="health", percent=86)
    assert notifier.edited == []


async def test_alerter_never_raises(app: Any, clock: Any) -> None:
    """Сбой самой системы оповещений уходит в лог и не роняет обработчик."""

    def broken_uow() -> Any:
        raise RuntimeError("база недоступна")

    alerter = AdminAlerter(uow=broken_uow, clock=clock, notifier=RecordingNotifier(), admin_chat_ids=[1])
    await alerter.alert("TG-NET", where="x")
