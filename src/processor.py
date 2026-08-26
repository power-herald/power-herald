import asyncio
import datetime
import logging
import signal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import get_config
from src.maintenance import is_maintenance
from src.models import PowerSource, PowerSourceGroup, PowerSourceType, StateChangeType
from src.notify import bot as notify_bot
from src.notify import notify_group_state_change, notify_state_change
from src.state_store import latest_change, latest_state, record_change

config = get_config()
logger = logging.getLogger("processor")

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)


def as_utc(timestamp):
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        return timestamp.replace(tzinfo=datetime.timezone.utc)
    return timestamp.astimezone(datetime.timezone.utc)


def current_state(session, source, timestamp):
    known = latest_change(session, source.id, stable_only=True)
    observed = latest_state(session, source.id, stable_only=True)
    if is_maintenance(source.id)[0]:
        return known.state if known else StateChangeType.OFFLINE
    if source.type == PowerSourceType.ACTIVE and (
        observed is None or as_utc(observed.last_updated_at) < timestamp - datetime.timedelta(
            seconds=config.active_probe_timeout
        )
    ):
        return StateChangeType.OFFLINE
    return observed.state if observed else StateChangeType.OFFLINE


def process_group(session, group, timestamp):
    changed = []
    for source in [source for source in group.sources if source.enabled]:
        logger.info("Processing state change for source: %s", source.name)
        state = current_state(session, source, timestamp)
        previous = latest_change(session, source.id, stable_only=True)
        logger.debug("Current state for %s: %s, previous state: %s", source.name, state.value, previous.state.value if previous else "None")
        if previous is None or previous.state != state:
            logger.warning("State changed for %s: %s", source.name, state.value)
            record_change(session, source.id, state, timestamp)
            changed.append((source, state))
    return changed


async def process_sources():
    session = Session()
    try:
        timestamp = datetime.datetime.now(datetime.timezone.utc)
        groups = session.query(PowerSourceGroup).all()
        grouped_ids = set()
        notifications = []
        for group in groups:
            logger.info("Processing state change for group: %s", group.name)
            enabled_sources = [source for source in group.sources if source.enabled]
            grouped_ids.update(source.id for source in enabled_sources)
            changed = process_group(session, group, timestamp)
            if changed:
                notifications.append((group, enabled_sources, changed))
        source_query = session.query(PowerSource).filter(PowerSource.enabled == True)
        if grouped_ids:
            source_query = source_query.filter(~PowerSource.id.in_(grouped_ids))
        for source in source_query.all():
            logger.info("Processing state change for source: %s", source.name)
            state = current_state(session, source, timestamp)
            previous = latest_change(session, source.id, stable_only=True)
            if previous is None or previous.state != state:
                logger.warning("State changed for %s: %s", source.name, state.value)
                record_change(session, source.id, state, timestamp)
                notifications.append((None, None, [(source, state)]))
        session.commit()

        logger.info("Committed state changes; notifications pending: %s", len(notifications))
        for group, enabled_sources, changed in notifications:
            if group and len(changed) == len(enabled_sources) and len({state for _, state in changed}) == 1:
                logger.warning("Sending grouped notification for %s sources in %s", len(changed), group.name)
                await notify_group_state_change(
                    group.id, changed[0][1], timestamp, [source.id for source, _ in changed]
                )
            else:
                for source, state in changed:
                    logger.warning("Sending notification for %s: %s", source.name, state.value)
                    await notify_state_change(source.id, state, timestamp)
    finally:
        session.close()


async def main():
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)
    try:
        logger.info("State processor started")
        while not stop_event.is_set():
            await process_sources()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=config.state_processor_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("Shutdown signal received")
    finally:
        await notify_bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())