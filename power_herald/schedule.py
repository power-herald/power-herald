import asyncio
import datetime as dt
import logging

from aiogram import Bot
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.config import get_config
from power_herald.messages import schedule_message_from_json
from power_herald.models import (
    Base,
    Chat,
    Outage,
    OutageData,
    OutageNotification,
    OutageNotificationType,
)
from power_herald.outage_data import content_hash, fetch_outage_data, message_hash, prepare_messages
from power_herald.lifecycle import use_stop_event

config = get_config()
logger = logging.getLogger("schedule")

async def update_once() -> bool:
    logger.info("Starting outage schedule update from %s", config.outage_data_source)
    engine = create_engine(config.db_url, **config.db_engine_options)
    Base.metadata.create_all(engine)
    data = fetch_outage_data(source=config.outage_data_source)
    current_hash = content_hash(data)
    logger.debug("Fetched outage data with content hash %s", current_hash)
    changed_messages: list[dict] = []
    with sessionmaker(bind=engine)() as session:
        previous = session.query(OutageData).order_by(OutageData.id.desc()).first()
        if previous and previous.content_hash == current_hash:
            logger.info("Outage data content is unchanged")
            previous.last_updated_at = config.now()
            previous.json = data
        elif previous:
            logger.info("Outage data content changed")
            previous.last_updated_at = config.now()
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
    await send_messages(config.bot_token, changed_messages, date=config.now().date(), updated=True)
    logger.info("Outage schedule update completed")
    return True


async def send_schedule_once(
    notification_type: OutageNotificationType, target_date: dt.date
) -> bool:
    today = config.now().date()
    engine = create_engine(config.db_url, **config.db_engine_options)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as session:
        previous_notification = (
            session.query(OutageNotification)
            .filter_by(type=notification_type)
            .order_by(OutageNotification.posted_at.desc())
            .first()
        )
        if previous_notification and previous_notification.posted_at.date() == today:
            logger.info("%s outage schedule was already sent for %s", notification_type.value, today)
            return False
        latest = session.query(OutageData).order_by(OutageData.id.desc()).first()
        if latest is None:
            logger.info("No outage data available; skipping %s outage schedule", notification_type.value)
            return False
        messages = list(prepare_messages(latest.json, config.gpvs, today=target_date).values())

    await send_messages(
        config.bot_token,
        messages,
        today=notification_type is OutageNotificationType.TODAY,
        date=target_date,
    )
    with sessionmaker(bind=engine)() as session:
        session.add(
            OutageNotification(
                posted_at=config.now(),
                type=notification_type,
            )
        )
        session.commit()
    logger.info("%s outage schedule sent for %s", notification_type.value, target_date)
    return True


async def send_messages(
    token: str, messages: list[dict],
    today: bool = True,
    date: dt.date | None = None,
    updated: bool = False,
) -> None:
    if not messages:
        logger.info("No changed outage messages to send")
        return
    engine = create_engine(config.db_url, **config.db_engine_options)
    bot = Bot(token=token)
    try:
        sent_at = config.now()
        with sessionmaker(bind=engine)() as session:
            chats = session.query(Chat).filter_by(enabled=True).all()
            logger.warning("Sending %s changed outage messages to %s enabled chats", len(messages), len(chats))
            for message in messages:
                rendered_message = schedule_message_from_json(
                    message,
                    date=(date or config.now().date()).isoformat(),
                    today=today,
                    as_of=sent_at,
                    updated=updated,
                )
                sent_count = 0
                for chat in chats:
                    try:
                        await bot.send_message(
                            chat.chat_id,
                            rendered_message,
                            message_thread_id=chat.thread_id,
                            parse_mode="MarkdownV2",
                        )
                        sent_count += 1
                    except Exception:
                        logger.exception("Failed to send outage message to %s", chat.chat_id)
                logger.warning("Sent outage message for %s to %s chats", message["name"], sent_count)
    finally:
        await bot.session.close()


async def main(stop_event=None) -> None:
    stop_event = use_stop_event(stop_event)

    logger.info("Schedule poster started")
    try:
        while not stop_event.is_set():
            try:
                await update_once()
            except Exception:
                logger.exception("Outage schedule update failed")
            now = config.now()
            if now.time() >= config.outage_schedule_send_time_today:
                try:
                    await send_schedule_once(
                        OutageNotificationType.TODAY,
                        now.date(),
                    )
                except Exception:
                    logger.exception("Today's outage schedule send failed")
            if now.time() >= config.outage_schedule_send_time_tomorrow:
                try:
                    await send_schedule_once(
                        OutageNotificationType.TOMORROW,
                        now.date() + dt.timedelta(days=1),
                    )
                except Exception:
                    logger.exception("Tomorrow's outage schedule send failed")
            logger.debug(
                "Waiting %s seconds before the next outage schedule update",
                config.outage_update_interval_seconds,
            )
            now = config.now()
            next_schedules = [
                dt.datetime.combine(
                    now.date(), schedule_time, tzinfo=now.tzinfo
                )
                for schedule_time in (
                    config.outage_schedule_send_time_today,
                    config.outage_schedule_send_time_tomorrow,
                )
            ]
            next_schedule = min(
                schedule + (dt.timedelta(days=1) if schedule <= now else dt.timedelta())
                for schedule in next_schedules
            )
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
    asyncio.run(main())
