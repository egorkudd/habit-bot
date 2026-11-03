"""Вход и роли (раздел 3.0). Без aiogram: те же сценарии потом вызовет HTTP API."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import UowFactory
from habit_bot.kernel.identity import Actor, Identity, Provider, Role, User, UserStatus

log = logging.getLogger(__name__)
ACTIVITY_STEP = timedelta(minutes=1)
DEFAULT_ADMIN_NAME = "Администратор"


class SignInTelegram:
    """Находит пользователя по Telegram-ID. Администратор из ADMIN_TG_IDS регистрируется без приглашения."""

    def __init__(self, *, uow: UowFactory, clock: Clock, admin_tg_ids: Iterable[int]) -> None:
        self._uow = uow
        self._clock = clock
        self._admins = frozenset(admin_tg_ids)

    async def execute(self, tg_id: int, display_name: str, *, channel: str = "telegram") -> Actor | None:
        now = self._clock.now()
        async with self._uow() as uow:
            found = await uow.session.execute(
                select(Identity)
                .options(selectinload(Identity.user))
                .where(Identity.provider == Provider.TELEGRAM, Identity.external_id == str(tg_id))
            )
            identity = found.scalar_one_or_none()
            if identity is not None:
                user = identity.user
                if user.status is UserStatus.BLOCKED:
                    return None
                if now - user.last_active_at >= ACTIVITY_STEP:
                    # Время активности не меняет версию и время изменения профиля.
                    await uow.session.execute(
                        update(User)
                        .where(User.id == user.id)
                        .values(last_active_at=now, updated_at=User.updated_at)
                        .execution_options(synchronize_session=False)
                    )
                return Actor(user_id=user.id, role=user.role, channel=channel, request_time=now)
            if tg_id not in self._admins:
                return None
            user = User(
                name=(display_name.strip() or DEFAULT_ADMIN_NAME)[:64],
                role=Role.ADMIN,
                status=UserStatus.ONBOARDING,
                last_active_at=now,
            )
            user.identities.append(Identity(provider=Provider.TELEGRAM, external_id=str(tg_id), created_at=now))
            uow.session.add(user)
            await uow.session.flush()
            log.info("Зарегистрирован администратор", extra={"user": user.id})
            return Actor(user_id=user.id, role=user.role, channel=channel, request_time=now)


class SyncAdminRoles:
    """Роль администратора определяется списком ADMIN_TG_IDS при каждом запуске (раздел 3.0)."""

    def __init__(self, *, uow: UowFactory, admin_tg_ids: Iterable[int]) -> None:
        self._uow = uow
        self._admins = frozenset(admin_tg_ids)

    async def execute(self) -> tuple[int, int]:
        """Возвращает (сколько стало администраторами, со скольких роль снята)."""
        promoted = demoted = 0
        async with self._uow() as uow:
            rows = await uow.session.execute(
                select(User, Identity.external_id)
                .join(Identity, Identity.user_id == User.id)
                .where(Identity.provider == Provider.TELEGRAM)
            )
            for user, external_id in rows.all():
                should_be_admin = int(external_id) in self._admins
                if should_be_admin and user.role is not Role.ADMIN:
                    user.role = Role.ADMIN
                    promoted += 1
                elif not should_be_admin and user.role is Role.ADMIN:
                    user.role = Role.USER
                    demoted += 1
        if promoted or demoted:
            log.info("Роли обновлены по ADMIN_TG_IDS: +%s / −%s", promoted, demoted)
        return promoted, demoted
