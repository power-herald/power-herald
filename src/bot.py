# src/bot.py
import logging
import signal
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import asyncio
from src.config import get_config

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
config = get_config()

bot = Bot(token=config.bot_token)
dp = Dispatcher()

# Import and include admin router
try:
    from src.admin import router as admin_router
    dp.include_router(admin_router)
except Exception as e:
    logging.warning(f"Admin router not loaded: {e}")

@dp.message()
async def echo_handler(message: types.Message):
    await message.answer("Hello! This is a Power Herald bot.\nChat ID is: " + str(message.chat.id) + "\nThread ID is: " + str(message.message_thread_id))

async def on_startup(app):
    await bot.set_webhook(config.webhook_url)
    logging.info(f"Webhook set to {config.webhook_url}")

async def on_shutdown(app):
    await bot.delete_webhook()
    logging.info("Webhook deleted")

async def main():
    logging.info(f"Bot webhook server starting on {config.webhook_address}:{config.webhook_port}{config.webhook_path}")
    logging.info(f"Bot webhook URL: {config.webhook_url}")
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
        logging.info(f"Bot webhook server started.")
        await stop_event.wait()
        logging.info("Shutdown signal received")
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
