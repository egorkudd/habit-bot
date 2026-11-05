from __future__ import annotations

from datetime import timedelta

from habit_bot.kernel.errors import AppError
from habit_bot.kernel.jobs import JobSpec
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.backup.usecases import SCHEDULE, Backups
from habit_bot.ops import backup_path

CHECK_EVERY = timedelta(hours=1)  # раз в час проверяем, прошло ли 2 дня с последнего удачного бэкапа


class BackupModule(Module):
    """Бэкап базы раз в 2 дня и «Бэкап сейчас» (раздел 3.13, часть 10)."""

    key = "backup"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        settings = ctx.settings
        backups = Backups(uow=ctx.uow, clock=ctx.clock, tz=ctx.services["days"].tz, db_path=settings.db_path,
                          target=backup_path(settings.data_dir), password=settings.backup_password,
                          alerter=ctx.services.get("alerter"))
        ctx.services["backup"] = backups

        channel = ctx.channel("telegram")
        if channel is None:  # pragma: no cover — без Telegram бэкап по расписанию некуда отправить
            return
        from habit_bot.channels.telegram.channel import TelegramChannel
        from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
        from habit_bot.modules.backup.telegram.handlers import KEY, build_backup_router, send_backup

        assert isinstance(channel, TelegramChannel)
        channel.add_router(build_backup_router(backups, channel.screens))
        channel.menu.add(MenuEntry(KEY, "💾 Бэкап", 40, Place.ADMIN, admin_only=True, ready=True))

        async def scheduled() -> bool:
            """Раз в 2 дня — файл каждому администратору; ошибку уже сообщило оповещение BKP-BOT."""
            if not await backups.due():
                return False
            try:
                made = await backups.make(SCHEDULE)
            except AppError:
                return False
            for chat_id in settings.admin_tg_ids:
                await send_backup(channel.bot, chat_id, made, backups)
            return True

        ctx.services["backup.scheduled"] = scheduled
        ctx.add_job(JobSpec("backup.schedule", CHECK_EVERY, scheduled, run_at_start=False))
