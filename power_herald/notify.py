# src/notify.py
import logging
import asyncio
from aiogram import Bot
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from power_herald.models import Chat, Outage, Period, PowerGroup, PowerSource, StateChangeType, Subscription
import os
import datetime
from power_herald.config import get_config
from power_herald.messages import generator_state_change_message, get_message, group_state_change_message, state_change_message

config = get_config()
logger = logging.getLogger("notifier")

engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)
bot = Bot(token=config.bot_token)


def close_resources() -> None:
    engine.dispose()


def next_outage_message(
    session,
    source: PowerSource | None,
    state: StateChangeType,
    timestamp: datetime.datetime,
) -> str | None:
    if not config.notifications_track_outages or (source and source.is_generator):
        return None

    outage = session.query(Outage).order_by(Outage.id.desc()).first()
    if outage is None:
        return None

    timestamp = timestamp.astimezone(config.timezone) if timestamp.tzinfo else timestamp.replace(tzinfo=config.timezone)
    next_state = StateChangeType.ONLINE if state == StateChangeType.OFFLINE else StateChangeType.OFFLINE
    for period in outage.message.get("outages", []):
        if period.get("status") != next_state.value:
            continue
        try:
            start_time = datetime.time.fromisoformat(period["start"])
        except (KeyError, TypeError, ValueError):
            continue
        start = datetime.datetime.combine(timestamp.date(), start_time, tzinfo=config.timezone)
        if start > timestamp:
            return get_message(f"notification.outage.next_{next_state.value}", start=period["start"])
    return None


async def notify_state_change(source_id: int, state: StateChangeType, timestamp: datetime.datetime):
    session = Session()
    try:
        source = session.query(PowerSource).get(source_id)
        if source is None:
            return
        subs = session.query(Subscription).filter_by(source_id=source.id, enabled=True).all()
        maintenance_window = None
        next_working_window = None
        if source.is_generator and source.generator is not None:
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                timestamp = timestamp.replace(tzinfo=config.timezone)
            else:
                timestamp = timestamp.astimezone(config.timezone)
            if state == StateChangeType.ONLINE:
                maint_start = timestamp + datetime.timedelta(minutes=source.generator.work_duration_minutes)
                maint_end = maint_start + datetime.timedelta(minutes=source.generator.maintenance_duration_minutes)
                maintenance_window = (maint_start.strftime("%H:%M"), maint_end.strftime("%H:%M"))
            elif state == StateChangeType.OFFLINE:
                work_start = timestamp + datetime.timedelta(minutes=source.generator.maintenance_duration_minutes)
                next_working_window = work_start.strftime("%H:%M")

        for sub in subs:
            chat = session.query(Chat).filter_by(enabled=True, id=sub.chat_id).first()
            if chat is None or chat.chat_id in config.admin_chat_ids:
                continue
            period = session.query(Period).filter(
                Period.source_id == source.id,
                Period.finished_at.isnot(None)
            ).order_by(Period.started_at.desc()).first()
            duration = period.finished_at - period.started_at if period and period.finished_at else None
            if not source.is_generator:
                msg = state_change_message(source.name, source.description, state.value, duration)
            else:
                msg = generator_state_change_message(
                    source.name, source.description, state.value, duration, maintenance_window, next_working_window
                )
            outage_message = next_outage_message(session, source, state, timestamp)
            if outage_message:
                msg = f"{msg}\n\n{outage_message}"
            await bot.send_message(chat.chat_id, msg, message_thread_id=chat.thread_id)
            logger.warning("Notified %s: %s", chat.title or chat.chat_id, msg.replace("\n", "↵"))
    finally:
        session.close()


async def notify_group_state_change(
    group_id: int,
    state: StateChangeType,
    timestamp: datetime.datetime,
    source_ids: list[int],
):
    session = Session()
    try:
        group = session.query(PowerGroup).get(group_id)
        if group is None:
            return
        sources = {source.id: source for source in group.sources if source.id in source_ids}
        durations = []
        for source in sources.values():
            period = session.query(Period).filter(
                Period.source_id == source.id,
                Period.finished_at.isnot(None),
            ).order_by(Period.started_at.desc()).first()
            durations.append((source.name, period.finished_at - period.started_at if period and period.finished_at else None))

        subscriptions = session.query(Subscription).filter(
            Subscription.source_id.in_(sources), Subscription.enabled == True
        ).all()
        chats = {}
        for subscription in subscriptions:
            chat = session.query(Chat).get(subscription.chat_id)
            if chat and chat.enabled:
                chats[chat.id] = chat

        message = group_state_change_message(group.name, group.description, state.value, durations)
        outage_message = next_outage_message(session, None, state, timestamp)
        if outage_message:
            message = f"{message}\n\n{outage_message}"
        for chat in chats.values():
            await bot.send_message(chat.chat_id, message, message_thread_id=chat.thread_id)
            logger.warning("Notified %s: %s", chat.title or chat.chat_id, message.replace("\n", "↵"))
    finally:
        session.close()

# Example usage: asyncio.run(notify_state_change(source_id, state, timestamp))
