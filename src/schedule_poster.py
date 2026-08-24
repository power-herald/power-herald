# src/schedule_poster.py
import asyncio
import logging
import datetime
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import Chat, Subscription, PowerSource, Base
from src.schedule import fetch_outage_data, format_outages_for_building
import os

BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
bot = Bot(token=BOT_TOKEN)

async def post_daily_schedules():
    session = Session()
    outages = fetch_outage_data()
    chats = session.query(Chat).filter_by(enabled=True).all()
    for chat in chats:
        # Find all sources this chat is subscribed to
        subs = session.query(Subscription).filter_by(chat_id=chat.id, enabled=True).all()
        building_ids = set()
        for sub in subs:
            source = session.query(PowerSource).get(sub.source_id)
            if source:
                building_ids.add(source.name)  # Assuming source.name is building_id
        for building_id in building_ids:
            text = format_outages_for_building(building_id, outages)
            await bot.send_message(chat.chat_id, text)
            logging.info(f"Posted schedule to {chat.chat_id} for {building_id}")
    session.close()

async def main():
    while True:
        now = datetime.datetime.now()
        # Schedule for 07:00 every day
        next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)
        if next_run < now:
            next_run += datetime.timedelta(days=1)
        wait_seconds = (next_run - now).total_seconds()
        logging.info(f"Waiting {wait_seconds/3600:.2f} hours until next schedule post.")
        await asyncio.sleep(wait_seconds)
        await post_daily_schedules()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
