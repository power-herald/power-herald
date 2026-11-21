import logging
from aiogram.exceptions import TelegramAPIError
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from power_herald.config import get_config, round_datetime_to_interval
from power_herald.lifecycle import use_stop_event
from power_herald.messages import format_duration, get_message
from power_herald.models import Chat, GeneratorStopNotification, PowerSource, PowerSourceType, StateChangeType
from power_herald.notify import bot, notify_state_change
from power_herald.state_store import latest_change, latest_state, record_change, record_state
import asyncio
import datetime

config = get_config()
logger = logging.getLogger("generator")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)


async def send_stop_reminders() -> None:
    lead_time = config.generator_stop_reminder
    if lead_time is None:
        return
    with Session() as session:
        sources = session.query(PowerSource).filter_by(enabled=True, is_generator=True).all()
        for source in sources:
            if source.generator is None:
                continue
            change = latest_change(session, source.id, stable_only=True)
            state = latest_state(session, source.id, stable_only=True)
            if not change or change.state != StateChangeType.ONLINE or not state or state.state != StateChangeType.ONLINE:
                continue
            started = change.timestamp
            if started.tzinfo is None or started.utcoffset() is None:
                started = started.replace(tzinfo=config.timezone)
            else:
                started = started.astimezone(config.timezone)
            deadline = round_datetime_to_interval(
                started + datetime.timedelta(minutes=source.generator.work_duration_minutes),
                config.generator_rounding,
            ).astimezone(datetime.timezone.utc)
            now = config.now().astimezone(datetime.timezone.utc)
            if not started.astimezone(datetime.timezone.utc) <= now < deadline or now < deadline - datetime.timedelta(seconds=lead_time):
                continue
            chats = session.query(Chat).filter_by(
                source_id=source.id, enabled=True, is_private=True,
            ).all()
            for chat in chats:
                if session.query(GeneratorStopNotification).filter_by(
                    state_change_id=change.id, chat_id=chat.id,
                ).first():
                    continue
                session.expire_all()
                current_change = latest_change(session, source.id, stable_only=True)
                current_state = latest_state(session, source.id, stable_only=True)
                now = config.now().astimezone(datetime.timezone.utc)
                if (
                    not current_change or current_change.id != change.id
                    or not current_state or current_state.state != StateChangeType.ONLINE
                    or not source.enabled or not source.is_generator or now >= deadline
                ):
                    break
                if not chat.enabled or not chat.is_private or chat.source_id != source.id:
                    continue
                remaining = deadline - now + datetime.timedelta(seconds=30)
                message = get_message(
                    "generator.time_to_stop",
                    source_name=source.name,
                    duration=format_duration(remaining),
                )
                try:
                    await bot.send_message(chat.chat_id, message, message_thread_id=chat.thread_id)
                except TelegramAPIError:
                    logger.exception("Failed to send generator stop reminder to chat %s", chat.chat_id)
                    continue
                session.add(GeneratorStopNotification(state_change_id=change.id, chat_id=chat.id))
                session.commit()
                logger.info("Sent generator stop reminder for %s to chat %s", source.name, chat.chat_id)


async def main(stop_event=None, ready_event=None):
    stop_event = use_stop_event(stop_event)
    try:
        lead_time = config.generator_stop_reminder
        if ready_event is not None:
            ready_event.set()
        if lead_time is None:
            await stop_event.wait()
            return
        while not stop_event.is_set():
            await send_stop_reminders()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass
    finally:
        engine.dispose()


async def set_generator_state(
    source_id: int,
    state: StateChangeType,
    maintenance_pause: bool = False,
    timestamp: datetime.datetime | None = None,
) -> bool:
    """Change a generator state and notify subscribed chats."""
    session = Session()
    source = session.query(PowerSource).filter_by(
        id=source_id, type=PowerSourceType.MANUAL, enabled=True
    ).first()
    if not source:
        session.close()
        return False

    last_state = latest_state(session, source.id, stable_only=True)

    if not last_state or last_state.state != state:
        timestamp = timestamp or config.now()
        _, changed = record_state(session, source.id, state, timestamp)
        if changed:
            record_change(session, source.id, state, timestamp)
        session.commit()
        logger.warning("Generator %s state changed to %s", source.name, state.value)
        session.close()
        await notify_state_change(source.id, state, timestamp, maintenance_pause=maintenance_pause)
        return True
    
    session.close()
    return False
