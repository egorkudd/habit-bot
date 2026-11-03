"""Каналы — через что пользователи работают с ботом. Сейчас один: Telegram (архитектура, раздел 1)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Channel(Protocol):
    name: str

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class ChannelRegistry:
    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def add(self, channel: Channel) -> None:
        if channel.name in self._channels:
            raise ValueError(f"Канал {channel.name} уже зарегистрирован")
        self._channels[channel.name] = channel

    def get(self, name: str) -> Channel | None:
        return self._channels.get(name)

    def all(self) -> list[Channel]:
        return list(self._channels.values())
