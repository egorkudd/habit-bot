"""Вход, приглашения, анкета, профиль и цели (раздел 3.0, 3.13). Без aiogram: те же сценарии потом вызовет HTTP API."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Iterable
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from habit_bot.kernel.clock import Clock
from habit_bot.kernel.db import Base, UowFactory
from habit_bot.kernel.domain.parsing import logical_day
from habit_bot.kernel.errors import AppError
from habit_bot.kernel.identity import Actor, Identity, Provider, Role, User, UserStatus
from habit_bot.modules.users.domain.city import City, pick_matches, resolve_local, short_region, suggest
from habit_bot.modules.users.domain.invites import check_invite
from habit_bot.modules.users.domain.kbju import (
    Activity,
    BodyInputs,
    Experience,
    GoalMode,
    Sex,
    Targets,
    age_on,
    calculate_targets,
)
from habit_bot.modules.users.dto import CityLookup, GoalView, InviteView, ProfileData, ProfileView
from habit_bot.modules.users.models import DEFAULT_TIMEZONE, BodyWeight, Goal, Invite, Profile
from habit_bot.platform.sources.geocoding import Geocoder, GeocoderUnavailable, Place

log = logging.getLogger(__name__)
ACTIVITY_STEP = timedelta(minutes=1)
DEFAULT_ADMIN_NAME = "Администратор"
DEFAULT_TZ = ZoneInfo(DEFAULT_TIMEZONE)
INVITE_CODE_BYTES = 8
RECALC_FIELDS = frozenset({"sex", "birth_date", "height_cm", "weight_kg", "activity", "mode"})


def _actor(user: User, now: datetime, channel: str) -> Actor:
    return Actor(user_id=user.id, role=user.role, channel=channel, request_time=now,
                 onboarding=user.status is UserStatus.ONBOARDING)


class SignInTelegram:
    """Находит пользователя по Telegram-ID; новый — только администратор из ADMIN_TG_IDS или по приглашению."""

    def __init__(self, *, uow: UowFactory, clock: Clock, admin_tg_ids: Iterable[int], tz: tzinfo = DEFAULT_TZ) -> None:
        self._uow = uow
        self._clock = clock
        self._admins = frozenset(admin_tg_ids)
        self._tz = tz

    async def execute(
        self, tg_id: int, display_name: str, *, invite_code: str | None = None, channel: str = "telegram",
    ) -> Actor:
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
                    raise AppError("ACCESS-BLOCKED")
                if now - user.last_active_at >= ACTIVITY_STEP:
                    # Время активности не меняет версию и время изменения профиля.
                    await uow.session.execute(
                        update(User)
                        .where(User.id == user.id)
                        .values(last_active_at=now, updated_at=User.updated_at)
                        .execution_options(synchronize_session=False)
                    )
                return _actor(user, now, channel)
            invite: Invite | None = None
            if tg_id not in self._admins:
                invite = await self._take_invite(uow.session, invite_code, now)
            user = User(
                name=(display_name.strip() or DEFAULT_ADMIN_NAME)[:64],
                role=Role.ADMIN if invite is None else Role.USER,
                status=UserStatus.ONBOARDING,
                last_active_at=now,
                invite_id=invite.id if invite else None,
            )
            user.identities.append(Identity(provider=Provider.TELEGRAM, external_id=str(tg_id), created_at=now))
            uow.session.add(user)
            await uow.session.flush()
            log.info("Зарегистрирован пользователь", extra={"user": user.id})
            return _actor(user, now, channel)

    async def _take_invite(self, session: AsyncSession, code: str | None, now: datetime) -> Invite:
        if not code:
            raise AppError("ACCESS-NO-INVITE")
        invite = (await session.execute(select(Invite).where(Invite.code == code.strip()))).scalar_one_or_none()
        if invite is None:
            raise AppError("ACCESS-NO-INVITE")
        check_invite(
            max_uses=invite.max_uses, uses=invite.uses, expires_at=invite.expires_at, revoked_at=invite.revoked_at,
            now=now, expires_local=invite.expires_at.astimezone(self._tz).date() if invite.expires_at else None,
        )
        invite.uses += 1
        return invite


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


class Invites:
    """Приглашения: создать, список действующих, отозвать (раздел 3.13). Только для администратора."""

    def __init__(self, *, uow: UowFactory, clock: Clock, tz: tzinfo = DEFAULT_TZ) -> None:
        self._uow = uow
        self._clock = clock
        self._tz = tz

    @staticmethod
    def _require_admin(actor: Actor) -> None:
        if not actor.is_admin:
            raise AppError("ACCESS-FOREIGN")

    def _view(self, invite: Invite) -> InviteView:
        local = invite.expires_at.astimezone(self._tz).date() if invite.expires_at else None
        return InviteView(invite.public_id.hex, invite.code, invite.max_uses, invite.uses, invite.expires_at, local)

    async def create(self, actor: Actor, *, max_uses: int, days: int) -> InviteView:
        self._require_admin(actor)
        now = self._clock.now()
        invite = Invite(
            code=secrets.token_urlsafe(INVITE_CODE_BYTES), created_by=actor.user_id, max_uses=max(1, max_uses),
            uses=0, expires_at=now + timedelta(days=days) if days > 0 else None, created_at=now,
        )
        async with self._uow() as uow:
            uow.session.add(invite)
            await uow.session.flush()
            return self._view(invite)

    async def active(self, actor: Actor) -> list[InviteView]:
        self._require_admin(actor)
        now = self._clock.now()
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(Invite).where(Invite.revoked_at.is_(None), Invite.uses < Invite.max_uses).order_by(Invite.id)
            )).scalars().all()
            return [self._view(i) for i in rows if i.expires_at is None or i.expires_at > now]

    async def revoke(self, actor: Actor, public_id: str) -> bool:
        self._require_admin(actor)
        async with self._uow() as uow:
            invites = (await uow.session.execute(select(Invite).where(Invite.revoked_at.is_(None)))).scalars().all()
            invite = next((i for i in invites if i.public_id.hex == public_id), None)
            if invite is None:
                return False
            invite.revoked_at = self._clock.now()
            return True


def _decimal(value: float | None) -> Decimal | None:
    return None if value is None else Decimal(str(value))


class Profiles:
    """Анкета, профиль, цели КБЖУ, удаление аккаунта (раздел 3.0, 4.1)."""

    def __init__(self, *, uow: UowFactory, clock: Clock, admin_tg_ids: Iterable[int], geocoder: Geocoder) -> None:
        self._uow = uow
        self._clock = clock
        self._admins = frozenset(admin_tg_ids)
        self._geocoder = geocoder

    # --- даты ---
    def today(self, tz: tzinfo = DEFAULT_TZ) -> date:
        return logical_day(self._clock.now(), tz)

    @staticmethod
    def inputs(data: ProfileData | ProfileView) -> BodyInputs:
        return BodyInputs(data.sex, data.birth_date, data.height_cm, data.weight_kg, data.activity, data.mode)

    def targets(self, data: ProfileData | ProfileView) -> Targets:
        return calculate_targets(self.inputs(data), self.today())

    # --- анкета ---
    async def complete_onboarding(
        self, actor: Actor, data: ProfileData, *, targets: Targets, source: str, starter_kit: Iterable[str] = (),
    ) -> GoalView:
        today = self.today()
        async with self._uow() as uow:
            user = await uow.session.get(User, actor.user_id)
            assert user is not None
            profile = (await uow.session.execute(
                select(Profile).where(Profile.user_id == actor.user_id)
            )).scalar_one_or_none() or Profile(user_id=actor.user_id)
            self._fill(profile, data)
            profile.starter_kit = list(starter_kit)
            uow.session.add(profile)
            user.name = data.name
            user.status = UserStatus.ACTIVE
            goal = self._goal(actor.user_id, data, targets, source, today)
            uow.session.add(goal)
            await self._weigh(uow.session, actor.user_id, today, data.weight_kg)
        return GoalView.of(targets, today, source, data.mode)

    @staticmethod
    def _fill(profile: Profile, data: ProfileData) -> None:
        profile.sex = data.sex.value
        profile.birth_date = data.birth_date
        profile.height_cm = float(data.height_cm)
        profile.weight_kg = float(data.weight_kg)
        profile.activity = data.activity.value
        profile.goal_mode = data.mode.value
        profile.target_weight = None if data.target_weight is None else float(data.target_weight)
        profile.experience = data.experience.value
        city = data.city
        profile.city_name = city.name if city else None
        profile.city_region = city.region if city else None
        profile.city_lat = city.latitude if city else None
        profile.city_lon = city.longitude if city else None
        profile.timezone = profile.timezone or DEFAULT_TIMEZONE

    def _goal(self, user_id: int, data: ProfileData | ProfileView, targets: Targets, source: str, day: date) -> Goal:
        snapshot: dict[str, Any] = {
            "sex": data.sex.value, "age": age_on(data.birth_date, day), "height_cm": str(data.height_cm),
            "weight_kg": str(data.weight_kg), "activity": data.activity.value, "mode": data.mode.value,
        }
        return Goal(
            user_id=user_id, start_date=day, kcal=targets.kcal, protein=targets.protein, fat=targets.fat,
            carbs=targets.carbs, mode=data.mode.value, source=source, inputs=snapshot,
            target_weight=None if data.target_weight is None else float(data.target_weight),
            created_at=self._clock.now(),
        )

    @staticmethod
    async def _weigh(session: AsyncSession, user_id: int, day: date, weight: Decimal) -> None:
        row = (await session.execute(
            select(BodyWeight).where(BodyWeight.user_id == user_id, BodyWeight.day == day)
        )).scalar_one_or_none()
        if row is None:
            session.add(BodyWeight(user_id=user_id, day=day, weight_kg=float(weight)))
        else:
            row.weight_kg = float(weight)
            row.deleted_at = None

    # --- профиль ---
    async def profile(self, actor: Actor) -> ProfileView | None:
        async with self._uow() as uow:
            profile = (await uow.session.execute(
                select(Profile).where(Profile.user_id == actor.user_id)
            )).scalar_one_or_none()
            user = await uow.session.get(User, actor.user_id)
            if profile is None or user is None:
                return None
            return self._profile_view(user, profile)

    def _profile_view(self, user: User, p: Profile) -> ProfileView:
        city = None
        if p.city_name:
            city = City(p.city_name, p.city_region or "", p.city_lat or 0.0, p.city_lon or 0.0)
        height, weight = _decimal(p.height_cm), _decimal(p.weight_kg)
        assert height is not None and weight is not None
        return ProfileView(
            name=user.name, sex=Sex(p.sex), birth_date=p.birth_date, age=age_on(p.birth_date, self.today()),
            height_cm=height, weight_kg=weight, activity=Activity(p.activity), mode=GoalMode(p.goal_mode),
            target_weight=_decimal(p.target_weight), experience=Experience(p.experience), city=city,
            timezone=p.timezone, starter_kit=tuple(p.starter_kit or ()),
        )

    async def update_profile(self, actor: Actor, **changes: Any) -> tuple[ProfileView, bool]:
        """Меняет поля профиля. Возвращает новый профиль и нужно ли предложить пересчёт КБЖУ."""
        today = self.today()
        async with self._uow() as uow:
            profile = (await uow.session.execute(
                select(Profile).where(Profile.user_id == actor.user_id)
            )).scalar_one()
            user = await uow.session.get(User, actor.user_id)
            assert user is not None
            for key, value in changes.items():
                if key == "name":
                    user.name = value
                elif key == "city":
                    profile.city_name = value.name if value else None
                    profile.city_region = value.region if value else None
                    profile.city_lat = value.latitude if value else None
                    profile.city_lon = value.longitude if value else None
                elif key == "mode":
                    profile.goal_mode = GoalMode(value).value
                elif key in {"height_cm", "weight_kg", "target_weight"}:
                    setattr(profile, key, None if value is None else float(value))
                elif key in {"sex", "activity", "experience"}:
                    setattr(profile, key, str(getattr(value, "value", value)))
                elif key == "birth_date":
                    profile.birth_date = value
                else:
                    raise KeyError(key)
            if "weight_kg" in changes:
                await self._weigh(uow.session, actor.user_id, today, Decimal(str(changes["weight_kg"])))
            await uow.session.flush()
            view = self._profile_view(user, profile)
        return view, bool(RECALC_FIELDS.intersection(changes))

    async def consume_starter(self, actor: Actor, key: str) -> bool:
        """Пункт стартового набора из анкеты применяется один раз: модуль забирает его из профиля."""
        async with self._uow() as uow:
            profile = (await uow.session.execute(
                select(Profile).where(Profile.user_id == actor.user_id)
            )).scalar_one_or_none()
            if profile is None or key not in (profile.starter_kit or []):
                return False
            profile.starter_kit = [k for k in profile.starter_kit if k != key]
            return True

    async def add_goal(self, actor: Actor, targets: Targets, *, start_date: date, source: str) -> GoalView:
        """Цель с заданной датой начала — для заполнения истории целей (раздел 3.12, часть 9)."""
        view = await self.profile(actor)
        assert view is not None
        async with self._uow() as uow:
            uow.session.add(self._goal(actor.user_id, view, targets, source, start_date))
        return GoalView.of(targets, start_date, source, None)

    async def delete_goal(self, actor: Actor, start_date: date, source: str) -> bool:
        """Убрать цель, заданную с этой даты (отмена команды текстом). Последняя цель не удаляется."""
        async with self._uow() as uow:
            goals = (await uow.session.execute(select(Goal).where(Goal.user_id == actor.user_id))).scalars().all()
            found = next((g for g in goals if g.start_date == start_date and g.source == source), None)
            if found is None or len(goals) <= 1:
                return False
            await uow.session.delete(found)
            return True

    # --- главный экран (раздел 3.1) ---
    async def home_layout(self, actor: Actor) -> list[str] | None:
        """Кнопки главного экрана в порядке пользователя; ``None`` — по умолчанию."""
        async with self._uow() as uow:
            layout = (await uow.session.execute(
                select(Profile.home_buttons).where(Profile.user_id == actor.user_id)
            )).scalar_one_or_none()
            return list(layout) if layout is not None else None

    async def set_home_layout(self, actor: Actor, keys: list[str] | None) -> None:
        async with self._uow() as uow:
            profile = (await uow.session.execute(
                select(Profile).where(Profile.user_id == actor.user_id)
            )).scalar_one()
            profile.home_buttons = None if keys is None else list(keys)

    # --- цели ---
    async def set_goal(self, actor: Actor, targets: Targets, *, source: str) -> GoalView:
        """Новая цель с датой начала «сегодня»; прошлые дни считаются по старой (раздел 3.0)."""
        view = await self.profile(actor)
        assert view is not None
        today = self.today()
        async with self._uow() as uow:
            uow.session.add(self._goal(actor.user_id, view, targets, source, today))
        return GoalView.of(targets, today, source, view.mode if source == "calc" else None)

    async def goals(self, actor: Actor) -> list[GoalView]:
        """История целей: новые сверху."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(
                select(Goal).where(Goal.user_id == actor.user_id).order_by(Goal.start_date.desc(), Goal.id.desc())
            )).scalars().all()
            return [
                GoalView(g.start_date, Decimal(str(g.kcal)), Decimal(str(g.protein)), Decimal(str(g.fat)),
                         Decimal(str(g.carbs)), g.source, GoalMode(g.mode) if g.mode else None)
                for g in rows
            ]

    async def weights_between(self, actor: Actor, start: date, end: date) -> dict[date, Decimal]:
        """Взвешивания за период — для светофора «Вес» и экспорта."""
        async with self._uow() as uow:
            rows = (await uow.session.execute(select(BodyWeight.day, BodyWeight.weight_kg).where(
                BodyWeight.user_id == actor.user_id, BodyWeight.deleted_at.is_(None), BodyWeight.day >= start,
                BodyWeight.day <= end))).all()
            return {day: Decimal(str(kg)) for day, kg in rows}

    async def goal_on(self, actor: Actor, day: date) -> GoalView | None:
        """Цель, действовавшая в эту дату; для дней раньше первой цели — первая (раздел 4.2)."""
        history = await self.goals(actor)
        if not history:
            return None
        return next((g for g in history if g.start_date <= day), history[-1])

    # --- город ---
    async def find_city(self, text: str) -> CityLookup:
        query, local = resolve_local(text)
        if local is not None:
            return CityLookup(query=query, city=local)
        try:
            places = await self._geocoder.search(query)
        except GeocoderUnavailable:
            raise AppError("CITY-SERVICE") from None
        matches = pick_matches(query, [_city(p) for p in places])
        if len(matches) == 1:
            return CityLookup(query=query, city=matches[0])
        if matches:
            return CityLookup(query=query, options=tuple(matches))
        return CityLookup(query=query, suggestions=tuple(suggest(query)))

    # --- удаление ---
    async def delete_account(self, actor: Actor) -> None:
        """Стирает все строки пользователя, включая Identity; в User остаётся обезличенная отметка (раздел 5)."""
        async with self._uow() as uow:
            session = uow.session
            if actor.is_admin:
                own = set((await session.execute(
                    select(Identity.external_id).where(Identity.user_id == actor.user_id)
                )).scalars().all())
                others = {str(i) for i in self._admins} - own
                if not others:
                    raise AppError("ACCESS-LAST-ADMIN")
            for table in reversed(Base.metadata.sorted_tables):
                if table.name != User.__tablename__ and "user_id" in table.c:
                    await session.execute(delete(table).where(table.c.user_id == actor.user_id))
            await session.execute(update(Invite).where(Invite.created_by == actor.user_id).values(created_by=None))
            await session.execute(
                update(User).where(User.id == actor.user_id).values(
                    name="", status=UserStatus.DELETED, role=Role.USER, invite_id=None,
                )
            )
        log.info("Аккаунт удалён", extra={"user": actor.user_id})

    async def count_user_rows(self, user_id: int) -> int:
        """Сколько строк пользователя осталось во всех таблицах (для проверки удаления)."""
        total = 0
        async with self._uow() as uow:
            for table in Base.metadata.sorted_tables:
                if "user_id" in table.c:
                    total += int((await uow.session.execute(
                        select(func.count()).select_from(table).where(table.c.user_id == user_id)
                    )).scalar_one())
        return total


def _city(place: Place) -> City:
    return City(place.name, short_region(place.region), place.latitude, place.longitude, place.country_code)
