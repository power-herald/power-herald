import asyncio
import datetime as dt
import logging
import signal

from aiogram import Bot
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import get_config
from src.messages import schedule_message_from_json
from src.models import Base, Chat, Outage, OutageData
from src.outage_data import content_hash, fetch_outage_data, message_hash, prepare_messages

logger = logging.getLogger("schedule")


async def update_once() -> bool:
    config = get_config()
    logger.info("Starting outage schedule update from %s", config.outage_data_source)
    engine = create_engine(config.db_url)
    Base.metadata.create_all(engine)
    data = fetch_outage_data(source=config.outage_data_source)
    current_hash = content_hash(data)
    logger.debug("Fetched outage data with content hash %s", current_hash)
    changed_messages: list[dict] = []
    with sessionmaker(bind=engine)() as session:
        previous = session.query(OutageData).order_by(OutageData.id.desc()).first()
        if previous and previous.content_hash == current_hash:
            logger.info("Outage data content is unchanged")
            previous.last_updated_at = dt.datetime.now(dt.timezone.utc)
            previous.json = data
        elif previous:
            logger.info("Outage data content changed")
            previous.last_updated_at = dt.datetime.now(dt.timezone.utc)
            previous.content_hash = current_hash
            previous.json = data
        else:
            logger.info("No previous outage data found; creating initial record")
            session.add(OutageData(content_hash=current_hash, json=data))
        prepared_count = 0
        outage_count = 0
        for name, message in prepare_messages(data, config.gpvs).items():
            prepared_count += 1
            if not message["outages"]:
                continue
            outage_count += len(message["outages"])
            current_message_hash = message_hash(message)
            latest = session.query(Outage).filter_by(name=name).order_by(Outage.id.desc()).first()
            if latest and latest.message_hash == current_message_hash:
                continue
            session.add(Outage(name=name, message_hash=current_message_hash, message=message))
            changed_messages.append(message)
        session.commit()
        logger.info(
            "Stored outage data for %s groups: %s outage periods, %s changed messages",
            prepared_count,
            outage_count,
            len(changed_messages),
        )
    await send_messages(config.bot_token, changed_messages)
    logger.info("Outage schedule update completed")
    return True


async def send_tomorrow_once() -> bool:
    config = get_config()
    target_date = dt.date.today() + dt.timedelta(days=1)
    engine = create_engine(config.db_url)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        latest = session.query(OutageData).order_by(OutageData.id.desc()).first()
        messages = list(prepare_messages(latest.json, config.gpvs, today=target_date).values())

    await send_messages(config.bot_token, messages, today=False)
    logger.info("Tomorrow's outage schedule sent for %s", target_date)
    return True


async def send_messages(token: str, messages: list[dict], today: bool = True) -> None:
    if not messages:
        logger.info("No changed outage messages to send")
        return
    config = get_config()
    engine = create_engine(config.db_url)
    bot = Bot(token=token)
    try:
        sent_at = dt.datetime.now()
        with sessionmaker(bind=engine)() as session:
            chats = session.query(Chat).filter_by(enabled=True).all()
            logger.info("Sending %s changed outage messages to %s enabled chats", len(messages), len(chats))
            for message in messages:
                rendered_message = schedule_message_from_json(message, today=today, as_of=sent_at)
                sent_count = 0
                for chat in chats:
                    try:
                        await bot.send_message(chat.chat_id, rendered_message, parse_mode="MarkdownV2")
                        sent_count += 1
                    except Exception:
                        logger.exception("Failed to send outage message to %s", chat.chat_id)
                logger.info("Sent outage message for %s to %s chats", message["name"], sent_count)
    finally:
        await bot.session.close()


async def main() -> None:
    config = get_config()
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    logger.info("Schedule poster started")
    try:
        while not stop_event.is_set():
            try:
                await update_once()
            except Exception:
                logger.exception("Outage schedule update failed")
            now = dt.datetime.now()
            if now.time() >= config.outage_schedule_send_time:
                try:
                    await send_tomorrow_once()
                except Exception:
                    logger.exception("Tomorrow's outage schedule send failed")
            logger.debug(
                "Waiting %s seconds before the next outage schedule update",
                config.outage_update_interval_seconds,
            )
            now = dt.datetime.now()
            next_schedule = dt.datetime.combine(now.date(), config.outage_schedule_send_time)
            if now >= next_schedule:
                next_schedule += dt.timedelta(days=1)
            wait_seconds = min(
                config.outage_update_interval_seconds,
                max(1, int((next_schedule - now).total_seconds())),
            )
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=wait_seconds,
                )
            except asyncio.TimeoutError:
                continue
    finally:
        logger.info("Shutdown signal received")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
