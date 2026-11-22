import asyncio
import datetime as dt
import logging

from aiogram.exceptions import TelegramAPIError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.config import get_config
from power_herald.emergency import is_emergency
from power_herald.lifecycle import use_stop_event
from power_herald.messages import format_clock, format_duration, get_message
from power_herald.models import Chat, Outage, OutageReminderNotification
from power_herald.notify import bot
from power_herald.outage_data import day_outages, is_unspecified

config = get_config()
logger = logging.getLogger("reminder")
engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)


def next_outage(message: dict, now: dt.datetime) -> dt.datetime | None:
    if message.get("emergency", False):
        return None
    local_now = now.astimezone(config.timezone)
    now_utc = now.astimezone(dt.timezone.utc)
    candidates = []
    for offset in range(8):
        date = local_now.date() + dt.timedelta(days=offset)
        if is_unspecified(message, date):
            continue
        for period in day_outages(message, date):
            if period.get("status") != "offline":
                continue
            try:
                start = dt.time.fromisoformat(period["start"])
                if start.tzinfo is not None:
                    raise ValueError("start time must not contain a timezone")
            except (KeyError, TypeError, ValueError):
                logger.warning("Invalid outage start time for %s: %r", date, period)
                continue
            if start == dt.time.min:
                previous_day = date - dt.timedelta(days=1)
                if any(
                    item.get("status") == "offline" and item.get("end") == "24:00"
                    for item in day_outages(message, previous_day)
                ):
                    continue
            candidate = dt.datetime.combine(date, start, tzinfo=config.timezone)
            if candidate.astimezone(dt.timezone.utc) > now_utc:
                candidates.append(candidate)
    return min(candidates, key=lambda value: value.astimezone(dt.timezone.utc), default=None)


async def send_outage_reminders() -> None:
    lead_time = config.notifications_next_scheduled_outage_reminder
    if lead_time is None or is_emergency():
        return
    with Session() as session:
        chats = session.query(Chat).filter(
            Chat.enabled.is_(True), Chat.outage_group_id.isnot(None)
        ).all()
        for chat in chats:
            session.expire_all()
            if not chat.enabled or chat.outage_group_id is None or is_emergency():
                continue
            outage = session.query(Outage).filter_by(
                outage_group_id=chat.outage_group_id
            ).order_by(Outage.id.desc()).first()
            if outage is None:
                continue
            now = config.now()
            start = next_outage(outage.message, now)
            if start is None:
                continue
            start_utc = start.astimezone(dt.timezone.utc)
            remaining = start_utc - now.astimezone(dt.timezone.utc)
            if remaining > dt.timedelta(seconds=lead_time):
                continue
            starts_at = start_utc.replace(tzinfo=None)
            if session.query(OutageReminderNotification).filter_by(
                chat_id=chat.id, outage_group_id=chat.outage_group_id, starts_at=starts_at
            ).first():
                continue
            message = get_message(
                "notification.outage.reminder",
                duration=format_duration(remaining + dt.timedelta(seconds=30)),
                start=format_clock(start.strftime("%H:%M")),
            )
            try:
                await bot.send_message(chat.chat_id, message, message_thread_id=chat.thread_id)
            except TelegramAPIError:
                logger.exception("Failed to send outage reminder to chat %s", chat.chat_id)
                continue
            session.add(OutageReminderNotification(
                chat_id=chat.id, outage_group_id=chat.outage_group_id, starts_at=starts_at
            ))
            session.commit()
            logger.info("Sent outage reminder to chat %s for %s", chat.chat_id, starts_at)


async def main(stop_event=None, ready_event=None) -> None:
    stop_event = use_stop_event(stop_event)
    logger.info("Outage reminder started")

    try:
        lead_time = config.notifications_next_scheduled_outage_reminder
        if ready_event is not None:
            ready_event.set()
        if lead_time is None:
            await stop_event.wait()
            return
        while not stop_event.is_set():
            try:
                await send_outage_reminders()
            except Exception:
                logger.exception("Outage reminder check failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
    finally:
        logger.info("Shutdown signal received")
        engine.dispose()
