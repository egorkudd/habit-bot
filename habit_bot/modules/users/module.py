from __future__ import annotations

from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.users.usecases import SignInTelegram, SyncAdminRoles


class UsersModule(Module):
    key = "users"
    stage = Stage.MVP

    def register(self, ctx: ModuleContext) -> None:
        sign_in = SignInTelegram(uow=ctx.uow, clock=ctx.clock, admin_tg_ids=ctx.settings.admin_tg_ids)
        sync_roles = SyncAdminRoles(uow=ctx.uow, admin_tg_ids=ctx.settings.admin_tg_ids)
        ctx.services["users.sign_in"] = sign_in
        ctx.services["users.sync_roles"] = sync_roles

        async def sync_on_startup() -> None:
            await sync_roles.execute()

        ctx.on_startup(sync_on_startup)

        channel = ctx.channel("telegram")
        if channel is not None:
            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.modules.users.telegram.handlers import AuthMiddleware, build_router

            assert isinstance(channel, TelegramChannel)
            channel.add_outer_middleware(AuthMiddleware(sign_in))
            channel.add_router(build_router())
