# src/bot.py
import logging
import sys
from aiogram import Bot, Dispatcher, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
import asyncio
import os
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
    await message.answer("Hello! This is a Power Herald bot.")

async def on_startup(app):
    await bot.set_webhook(config.webhook_url)
    logging.info(f"Webhook set to {config.webhook_url}")

async def on_shutdown(app):
    await bot.delete_webhook()
    logging.info("Webhook deleted")

async def main():
    app = web.Application()
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=config.webhook_path)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    setup_application(app, dp, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logging.info("Bot webhook server started on port 8080")
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
