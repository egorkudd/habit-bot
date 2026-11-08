from __future__ import annotations

from datetime import timedelta

from habit_bot.kernel.identity import Actor
from habit_bot.kernel.jobs import JobSpec
from habit_bot.kernel.modules import Module, ModuleContext, Stage
from habit_bot.modules.ai_commands.planner import Services
from habit_bot.modules.ai_commands.usecases import TextCommands
from habit_bot.platform.ai.budget import Budget
from habit_bot.platform.ai.client import LlmClient, build_client

PURGE_EVERY = timedelta(hours=24)


class AiCommandsModule(Module):
    """Команды текстом и заполнение через ИИ (раздел 3.10, 3.12, часть 9). Без ключа модели — выключено,
    кнопки работают как обычно."""

    key = "ai_commands"
    stage = Stage.MVP
    depends_on = ("users", "days")

    def register(self, ctx: ModuleContext) -> None:
        settings = ctx.settings
        client: LlmClient | None = ctx.services.get("llm.client") or build_client(
            base_url=settings.llm_base_url, model=settings.llm_model, api_key=settings.llm_api_key,
            fallback=(settings.llm_fallback_base_url, settings.llm_fallback_model, settings.llm_fallback_api_key))
        days = ctx.services["days"]
        services = Services(days=days, profiles=ctx.services["users.profiles"], food=ctx.services.get("food"),
                            warmup=ctx.services.get("warmup"), habits=ctx.services.get("habits"),
                            workouts=ctx.services.get("workouts"), runs=ctx.services.get("runs"))
        commands = TextCommands(uow=ctx.uow, clock=ctx.clock, tz=days.tz, client=client,
                                budget=Budget(uow=ctx.uow, monthly_usd=settings.llm_monthly_budget_usd),
                                services=services, alerter=ctx.services.get("alerter"))
        ctx.services["ai_commands"] = commands

        async def purge() -> int:
            return await commands.purge()

        ctx.add_job(JobSpec("ai_commands.purge", PURGE_EVERY, purge))

        channel = ctx.channel("telegram")
        if channel is not None:
            from aiogram.types import InlineKeyboardButton

            from habit_bot.channels.telegram.channel import TelegramChannel
            from habit_bot.channels.telegram.ui.menu import MenuEntry, Place
            from habit_bot.modules.ai_commands.telegram.handlers import FILL_KEY, build_ai_router

            assert isinstance(channel, TelegramChannel)
            save_button = None
            if services.food is not None:
                from habit_bot.modules.food.telegram.handlers import EntryCb

                def save_button(actor: Actor, entry_id: str, name: str) -> InlineKeyboardButton:
                    minute = int(days.now().timestamp() // 60)
                    return InlineKeyboardButton(text=f"💾 «{name}» как рецепт"[:60], callback_data=EntryCb(
                        o=actor.user_id, t=0, a="save", i=entry_id, m=minute).pack())

            router, free_text = build_ai_router(commands, channel.screens, lambda: channel.day_card, save_button)
            channel.add_router(router)
            channel.add_router(free_text, last=True)
            # «✍️ Текстом» в «Ещё» убрана (правки 1.0.2): фразы можно писать в чат сразу, старая кнопка работает
            channel.menu.add(MenuEntry(FILL_KEY, "📥 Импорт", 5, Place.SETTINGS, ready=True))
