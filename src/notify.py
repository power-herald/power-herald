# src/notify.py
import logging
import asyncio
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, OutagePeriod, Chat, Subscription, StateChangeType, PowerSourceType, GeneratorSession, Base
import os
import datetime
from src.config import get_config
from src.messages import state_change_message

config = get_config()
engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)
bot = Bot(token=config.bot_token)

async def notify_state_change(source_id: int, state: StateChangeType, timestamp: datetime.datetime):
    session = Session()
    source = session.query(PowerSource).get(source_id)
    if source is None:
        session.close()
        return
    subs = session.query(Subscription).filter_by(source_id=source.id, enabled=True).all()
    for sub in subs:
        chat = session.query(Chat).get(sub.chat_id)
        if chat is None:
            continue
        if not chat.enabled:
            continue
        
        # Skip generator notifications if not opted in
        if source.type == PowerSourceType.GENERATOR and not sub.notify_generator:
            continue
        
        # Stable transitions open a new period, so use the period just closed.
        period = session.query(OutagePeriod).filter(
            OutagePeriod.source_id == source.id,
            OutagePeriod.finished_at.isnot(None)
        ).order_by(OutagePeriod.started_at.desc()).first()
        duration = None
        if period and period.finished_at:
            duration = period.finished_at - period.started_at
        
        maintenance_window = None
        next_working_window = None
        # Generator-specific messages with maintenance windows
        if source.type == PowerSourceType.GENERATOR:
            if state == StateChangeType.ONLINE:
                # Generator started - show maintenance window
                maint_start = timestamp + datetime.timedelta(minutes=source.work_duration_minutes)
                maint_end = maint_start + datetime.timedelta(minutes=source.maintenance_duration_minutes)
                maintenance_window = (maint_start.strftime("%H:%M"), maint_end.strftime("%H:%M"))
                # Create generator session record
                gen_session = GeneratorSession(
                    source_id=source.id,
                    started_at=timestamp,
                    maintenance_window_start=maint_start,
                    maintenance_window_end=maint_end
                )
                session.add(gen_session)
                session.commit()
            elif state == StateChangeType.OFFLINE:
                # Generator stopped - show next working window
                work_start = timestamp + datetime.timedelta(minutes=source.maintenance_duration_minutes)
                next_working_window = work_start.strftime("%H:%M")
                # Update generator session record
                gen_session = session.query(GeneratorSession).filter_by(source_id=source.id, stopped_at=None).first()
                if gen_session:
                    gen_session.stopped_at = timestamp
                    session.commit()
        
        msg = state_change_message(source.name, state.value, duration, maintenance_window, next_working_window)
        await bot.send_message(chat.chat_id, msg)
        logging.info(f"Notified {chat.title or chat.chat_id}: {msg}")
    session.close()

# Example usage: asyncio.run(notify_state_change(source_id, state, timestamp))
