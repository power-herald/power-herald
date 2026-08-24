# src/notify.py
import logging
import asyncio
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerStateChange, OutagePeriod, Chat, Subscription, StateChangeType, PowerSourceType, GeneratorSession, Base
import os
import datetime

# Placeholders for config
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN")
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)
bot = Bot(token=BOT_TOKEN)

async def notify_state_change(state_change: PowerStateChange):
    session = Session()
    source = session.query(PowerSource).get(state_change.source_id)
    subs = session.query(Subscription).filter_by(source_id=source.id, enabled=True).all()
    for sub in subs:
        chat = session.query(Chat).get(sub.chat_id)
        if not chat.enabled:
            continue
        
        # Skip generator notifications if not opted in
        if source.type == PowerSourceType.GENERATOR and not sub.notify_generator:
            continue
        
        # Find last outage period for duration
        period = session.query(OutagePeriod).filter_by(source_id=source.id).order_by(OutagePeriod.started_at.desc()).first()
        duration = None
        if period and period.finished_at:
            duration = period.finished_at - period.started_at
        
        msg = f"{source.name}: {state_change.state.value.upper()}"
        if duration:
            msg += f"\nPrevious period: {str(duration).split('.')[0]}"
        
        # Generator-specific messages with maintenance windows
        if source.type == PowerSourceType.GENERATOR:
            if state_change.state == StateChangeType.ONLINE:
                # Generator started - show maintenance window
                maint_start = state_change.timestamp + datetime.timedelta(minutes=source.work_duration_minutes)
                maint_end = maint_start + datetime.timedelta(minutes=source.maintenance_duration_minutes)
                msg += f"\nMaintenance window: {maint_start.strftime('%H:%M')} - {maint_end.strftime('%H:%M')}"
                # Create generator session record
                gen_session = GeneratorSession(
                    source_id=source.id,
                    started_at=state_change.timestamp,
                    maintenance_window_start=maint_start,
                    maintenance_window_end=maint_end
                )
                session.add(gen_session)
                session.commit()
            elif state_change.state == StateChangeType.OFFLINE:
                # Generator stopped - show next working window
                work_start = state_change.timestamp + datetime.timedelta(minutes=source.maintenance_duration_minutes)
                msg += f"\nNext working window: {work_start.strftime('%H:%M')} onwards"
                # Update generator session record
                gen_session = session.query(GeneratorSession).filter_by(source_id=source.id, stopped_at=None).first()
                if gen_session:
                    gen_session.stopped_at = state_change.timestamp
                    session.commit()
        
        await bot.send_message(chat.chat_id, msg)
        logging.info(f"Notified {chat.title or chat.chat_id}: {msg}")
    session.close()

# Example usage: asyncio.run(notify_state_change(state_change))
