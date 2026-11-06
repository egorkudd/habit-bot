"""Реестры модулей и каналов (архитектура, раздел 6)."""

from typing import Any, ClassVar

import pytest

from habit_bot.kernel.channels import ChannelRegistry
from habit_bot.kernel.modules import Module, ModuleContext, ModuleError, ModuleRegistry, Stage


class NeedsFood(Module):
    key: ClassVar[str] = "needs_food"
    stage: ClassVar[Stage] = Stage.LAB
    depends_on: ClassVar[tuple[str, ...]] = ("food",)

    def register(self, ctx: ModuleContext) -> None:
        raise AssertionError("не должен регистрироваться")


def test_unknown_module() -> None:
    """Неизвестный модуль в ENABLED_MODULES — понятная ошибка."""
    with pytest.raises(ModuleError, match="Модуль food неизвестен"):
        ModuleRegistry({}).load(("food",))


def test_missing_dependency() -> None:
    """Модуль без нужных ему модулей не загружается."""
    registry = ModuleRegistry({"needs_food": f"{__name__}:NeedsFood"})
    with pytest.raises(ModuleError, match="нужны модули: food"):
        registry.load(("needs_food",))


class _Channel:
    name = "telegram"

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


def test_channel_registry() -> None:
    """Канал регистрируется один раз; отсутствующий канал — None."""
    registry = ChannelRegistry()
    channel = _Channel()
    registry.add(channel)
    assert registry.get("telegram") is channel
    assert registry.get("http") is None
    assert registry.all() == [channel]
    with pytest.raises(ValueError):
        registry.add(_Channel())


def test_app_wiring(app: Any) -> None:
    """Модуль users подключён: сервисы, хук запуска и Telegram-канал."""
    assert [m.key for m in app.registry.modules] == [
        "users", "days", "food", "warmup", "habits", "runs", "workouts", "stats", "export", "admin", "backup",
        "ai_commands"]
    assert "users.sign_in" in app.ctx.services
    assert app.ctx.channel("telegram") is app.telegram
    assert app.ctx.startup_hooks
