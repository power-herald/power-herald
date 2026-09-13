# src/weekly_stats.py
import datetime as dt
import logging

from aiogram import Bot
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker

from power_herald.config import get_config
from power_herald.messages import weekly_statistics_message
from power_herald.models import (
    Base,
    Chat,
    Period,
    PowerSource,
    StateChangeType,
    Subscription,
    WeeklyStatisticsNotification,
)

config = get_config()
logger = logging.getLogger("weekly_stats")

BLOCK_HOURS = 2
BLOCKS_PER_DAY = 24 // BLOCK_HOURS


def _week_bounds(reference_date: dt.date) -> tuple[dt.date, dt.date]:
    """Return the previous week's Monday (inclusive) and following Monday (exclusive)."""
    this_monday = reference_date - dt.timedelta(days=reference_date.weekday())
    return this_monday - dt.timedelta(days=7), this_monday


def _localize(value: dt.datetime, tzinfo) -> dt.datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=tzinfo)
    return value.astimezone(tzinfo)


def _overlap(
    start: dt.datetime, end: dt.datetime, window_start: dt.datetime, window_end: dt.datetime
) -> tuple[dt.datetime, dt.datetime] | None:
    overlap_start = max(start, window_start)
    overlap_end = min(end, window_end)
    if overlap_end <= overlap_start:
        return None
    return overlap_start, overlap_end


def compute_source_weekly_stats(
    session,
    source_id: int,
    week_start: dt.date,
    week_end: dt.date,
    now: dt.datetime,
    tzinfo,
) -> list[tuple[list[str], dt.timedelta]]:
    """Return, per weekday (Mon..Sun), the 2-hour block statuses and total offline time."""
    week_start_dt = dt.datetime.combine(week_start, dt.time.min, tzinfo=tzinfo)
    week_end_dt = dt.datetime.combine(week_end, dt.time.min, tzinfo=tzinfo)

    periods = (
        session.query(Period)
        .filter(
            Period.source_id == source_id,
            Period.started_at < week_end_dt,
            or_(Period.finished_at.is_(None), Period.finished_at > week_start_dt),
        )
        .order_by(Period.started_at.asc())
        .all()
    )
    clipped = []
    for period in periods:
        started_at = _localize(period.started_at, tzinfo)
        finished_at = _localize(period.finished_at, tzinfo) if period.finished_at else now
        overlap = _overlap(started_at, finished_at, week_start_dt, week_end_dt)
        if overlap:
            clipped.append((overlap[0], overlap[1], period.state))

    days = []
    for day_index in range(7):
        day_start = week_start_dt + dt.timedelta(days=day_index)
        blocks = []
        offline_seconds = 0.0
        for block_index in range(BLOCKS_PER_DAY):
            block_start = day_start + dt.timedelta(hours=block_index * BLOCK_HOURS)
            block_end = block_start + dt.timedelta(hours=BLOCK_HOURS)
            online_seconds = 0.0
            block_offline_seconds = 0.0
            for start, end, state in clipped:
                overlap = _overlap(start, end, block_start, block_end)
                if not overlap:
                    continue
                duration = (overlap[1] - overlap[0]).total_seconds()
                if state == StateChangeType.ONLINE:
                    online_seconds += duration
                else:
                    block_offline_seconds += duration
            offline_seconds += block_offline_seconds
            if online_seconds and block_offline_seconds:
                blocks.append("mixed")
            elif block_offline_seconds:
                blocks.append("offline")
            else:
                blocks.append("online")
        days.append((blocks, dt.timedelta(seconds=offline_seconds)))
    return days


async def send_weekly_statistics_once(reference_date: dt.date) -> bool:
    week_start, week_end = _week_bounds(reference_date)
    engine = create_engine(config.db_url, **config.db_engine_options)
    Base.metadata.create_all(engine)
    bot = Bot(token=config.bot_token)
    sent_any = False
    try:
        now = config.now()
        with sessionmaker(bind=engine)() as session:
            sources = session.query(PowerSource).filter_by(enabled=True).all()
            for source in sources:
                already_sent = session.query(WeeklyStatisticsNotification).filter_by(
                    source_id=source.id, week_start=week_start
                ).first()
                if already_sent:
                    continue

                days = compute_source_weekly_stats(session, source.id, week_start, week_end, now, config.timezone)
                message = weekly_statistics_message(
                    source.name,
                    week_start.isoformat(),
                    (week_end - dt.timedelta(days=1)).isoformat(),
                    days,
                )
                subscriptions = session.query(Subscription).filter_by(source_id=source.id, enabled=True).all()
                chats = [
                    chat
                    for chat in (
                        session.query(Chat).filter_by(id=subscription.chat_id, enabled=True).first()
                        for subscription in subscriptions
                    )
                    if chat is not None and chat.chat_id not in config.admin_chat_ids
                ]
                sent_count = 0
                for chat in chats:
                    try:
                        await bot.send_message(
                            chat.chat_id, message, message_thread_id=chat.thread_id, parse_mode="MarkdownV2"
                        )
                        sent_count += 1
                    except Exception:
                        logger.exception("Failed to send weekly outage statistics to %s", chat.chat_id)
                session.add(WeeklyStatisticsNotification(source_id=source.id, week_start=week_start, sent_at=now))
                session.commit()
                logger.info("Sent weekly outage statistics for %s to %s chats", source.name, sent_count)
                sent_any = sent_any or sent_count > 0
    finally:
        await bot.session.close()
    return sent_any
