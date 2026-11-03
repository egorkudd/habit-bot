from __future__ import annotations

from habit_bot.kernel.identity import Actor, User
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.users.usecases import Invites, Profiles, SignInTelegram, SyncAdminRoles
from habit_bot.platform.sources.geocoding import CachedGeocoder, Geocoder, OpenMeteoGeocoder


class UsersModule(Module):
    key = "users"
    stage = Stage.MVP

    def register(self, ctx: ModuleContext) -> None:
        admins = ctx.settings.admin_tg_ids
        sign_in = SignInTelegram(uow=ctx.uow, clock=ctx.clock, admin_tg_ids=admins)
        sync_roles = SyncAdminRoles(uow=ctx.uow, admin_tg_ids=admins)
        geocoder: Geocoder = ctx.services.get("geocoder") or OpenMeteoGeocoder()
        profiles = Profiles(
            uow=ctx.uow, clock=ctx.clock, admin_tg_ids=admins,
            geocoder=CachedGeocoder(geocoder, uow=ctx.uow, clock=ctx.clock),
        )
        invites = Invites(uow=ctx.uow, clock=ctx.clock)
        ctx.services.update({
            "users.sign_in": sign_in, "users.sync_roles": sync_roles, "users.profiles": profiles,
            "users.invites": invites,
        })

        async def sync_on_startup() -> None:
            await sync_roles.execute()

        ctx.on_startup(sync_on_startup)

        async def name_of(actor: Actor) -> str:
            async with ctx.uow() as uow:
                user = await uow.session.get(User, actor.user_id)
                return user.name if user else ""

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.users.telegram.admin import build_admin_router
            from habit_bot.modules.users.telegram.handlers import AuthMiddleware, build_router
            from habit_bot.modules.users.telegram.onboarding import OnboardingFlow, build_onboarding_router
            from habit_bot.modules.users.telegram.settings import SettingsFlow, build_settings_router

            assert isinstance(channel, TelegramChannel)
            channel.add_outer_middleware(AuthMiddleware(sign_in))
            channel.add_router(build_onboarding_router(OnboardingFlow(profiles, channel.screens)), first=True)
            channel.add_router(build_router(channel.menu, name_of))
            channel.add_router(build_settings_router(SettingsFlow(profiles, channel.screens)))
            channel.add_router(build_admin_router(invites, channel.screens))
            channel.menu.mark_ready("settings")
            channel.menu.mark_ready("admin")
