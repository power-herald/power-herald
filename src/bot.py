# src/bot.py
import logging
import signal
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat, BotCommandScopeAllChatAdministrators
from aiohttp import web
import asyncio
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import Chat
from src.config import get_config
from src.messages import bot_greeting
from src.admin import chat_is_admin, chat_is_enabled, generator_keyboard, router as admin_router

config = get_config()
logger = logging.getLogger("bot")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)
bot = Bot(token=config.bot_token)
dp = Dispatcher()

# Import and include admin router
try:
    dp.include_router(admin_router)
except Exception as e:
    logger.warning("Admin router not loaded: %s", e)

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    reply_markup = generator_keyboard() if (
        message.chat.type == "private"
        and (chat_is_enabled(message.chat.id) and not chat_is_admin(message.chat.id))
    ) else None
    await message.answer(
        bot_greeting(message.chat.id, message.message_thread_id),
        reply_markup=reply_markup,
    )


async def configure_command_menu() -> None:
    user_commands = [
        BotCommand(command="activate", description="Request chat activation"),
    ]
    activated_user_commands = [
        BotCommand(command="generator", description="Start or stop Generator"),
    ]
    admin_commands = activated_user_commands + [
        BotCommand(command="approve", description="Approve a chat activation"),
        BotCommand(command="subscribe", description="Subscribe a chat to a source"),
        BotCommand(command="sources", description="List power sources"),
        BotCommand(command="chats", description="List chats"),
        BotCommand(command="maintenance", description="Toggle maintenance mode"),
    ]

    await bot.set_my_commands(
        user_commands,
        scope=BotCommandScopeAllPrivateChats(),
    )
    await bot.set_my_commands(
        admin_commands,
        scope=BotCommandScopeAllChatAdministrators(),
    )

    session = Session()
    chats = session.query(Chat).filter_by(enabled=True).all()
    for chat in chats:
        await bot.set_my_commands(
            activated_user_commands if chat.is_private else [],
            scope=BotCommandScopeChat(chat_id=chat.chat_id),
        )
    for chat_id in config.admin_chat_ids:
        await bot.set_my_commands(
            admin_commands,
            scope=BotCommandScopeChat(chat_id=chat_id),
        )


async def on_startup(app):
    await configure_command_menu()
    await bot.set_webhook(config.webhook_url)
    logger.info("Webhook set to %s", config.webhook_url)

async def on_shutdown(app):
    await bot.delete_webhook()
    logger.info("Webhook deleted")

async def main():
    logger.info("Bot webhook server starting on %s:%s%s", config.webhook_address, config.webhook_port, config.webhook_path)
    logger.info("Bot webhook URL: %s", config.webhook_url)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=config.webhook_path)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, config.webhook_address, int(config.webhook_port))
    try:
        await site.start()
        logger.info("Bot webhook server started.")
        await stop_event.wait()
        logger.info("Shutdown signal received")
    finally:
        try:
            await runner.cleanup()
        finally:
            await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
