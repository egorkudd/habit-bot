"""Модули — что умеет продукт. Каждый регистрирует свои части в ``ModuleContext`` (архитектура, раздел 6)."""

from __future__ import annotations

import importlib
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar

from habit_bot.kernel.channels import Channel, ChannelRegistry
from habit_bot.kernel.clock import Clock
from habit_bot.kernel.config import Settings
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.events import EventBus
from habit_bot.kernel.idempotency import IdempotencyStore
from habit_bot.kernel.jobs import JobSpec


class Stage(StrEnum):
    MVP = "MVP"
    V2 = "v2"
    V3 = "v3"
    LAB = "lab"


StartupHook = Callable[[], Awaitable[None]]


@dataclass
class ModuleContext:
    """Что ядро даёт модулям. Новая точка расширения — новое поле здесь, интерфейс модулей не меняется."""

    settings: Settings
    clock: Clock
    uow: UowFactory
    events: EventBus
    idempotency: IdempotencyStore
    channels: ChannelRegistry
    services: dict[str, Any] = field(default_factory=dict)
    startup_hooks: list[StartupHook] = field(default_factory=list)
    jobs: list[JobSpec] = field(default_factory=list)

    def channel(self, name: str) -> Channel | None:
        return self.channels.get(name)

    def on_startup(self, hook: StartupHook) -> None:
        self.startup_hooks.append(hook)

    def add_job(self, job: JobSpec) -> None:
        self.jobs.append(job)


class Module(ABC):
    key: ClassVar[str]
    stage: ClassVar[Stage]
    depends_on: ClassVar[tuple[str, ...]] = ()

    @abstractmethod
    def register(self, ctx: ModuleContext) -> None:
        """Регистрирует сценарии, кнопки, задачи и подписки на события."""


class ModuleError(Exception):
    pass


class ModuleRegistry:
    """Загружает модули из ``ENABLED_MODULES`` и проверяет зависимости."""

    def __init__(self, known: Mapping[str, str]) -> None:
        self._known = dict(known)
        self.modules: list[Module] = []

    def load(self, enabled: tuple[str, ...]) -> None:
        for key in enabled:
            if key not in self._known:
                raise ModuleError(f"Модуль {key} неизвестен")
            module_path, _, class_name = self._known[key].partition(":")
            cls = getattr(importlib.import_module(module_path), class_name)
            self.modules.append(cls())
        loaded = {m.key for m in self.modules}
        for module in self.modules:
            missing = [dep for dep in module.depends_on if dep not in loaded]
            if missing:
                raise ModuleError(f"Модулю {module.key} нужны модули: {', '.join(missing)}")

    def register_all(self, ctx: ModuleContext) -> None:
        for module in self.modules:
            module.register(ctx)
