"""Run all Power Herald services in one asyncio daemon."""

import asyncio
import logging
import os

from sqlalchemy import create_engine

from power_herald import active_probe, bot, processor, probe, schedule
from power_herald.config import get_config
from power_herald.lifecycle import create_stop_event
from power_herald.models import Base

logger = logging.getLogger("server")


def _signal_ready() -> None:
    """Touch the ready file so OpenRC's start_post can stop waiting."""
    ready_file = os.environ.get("PH_READY_FILE")
    if not ready_file:
        return
    with open(ready_file, "w"):
        pass


def _clear_ready() -> None:
    ready_file = os.environ.get("PH_READY_FILE")
    if ready_file:
        try:
            os.remove(ready_file)
        except FileNotFoundError:
            pass


async def _wait_until_ready(services: list[asyncio.Task], ready_events: list[asyncio.Event]) -> None:
    """Wait until every service reports readiness, or stop early if one exits first."""
    waiters = [asyncio.ensure_future(event.wait()) for event in ready_events]
    pending = set(waiters) | set(services)
    try:
        while not all(waiter.done() for waiter in waiters):
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            if any(task in done for task in services):
                return
    finally:
        for waiter in waiters:
            waiter.cancel()


def init_database() -> None:
    """Create missing tables so a fresh database is usable without running ph-cli first."""
    config = get_config()
    if config.db_driver == "sqlite" and config.db_file_path:
        if os.path.exists(config.db_file_path):
            logger.info("SQLite database file already exists, skipping table creation")
            return
        logger.warning("SQLite database file does not exist, creating tables")
        engine = create_engine(config.db_url, **config.db_engine_options)
        Base.metadata.create_all(engine)
        engine.dispose()
        return


async def main() -> None:
    init_database()
    stop_event = create_stop_event()
    ready_events = [asyncio.Event() for _ in range(5)]
    services = [
        asyncio.create_task(bot.main(stop_event, ready_events[0]), name="bot"),
        asyncio.create_task(probe.main(stop_event, ready_events[1]), name="passive-probe"),
        asyncio.create_task(active_probe.main(stop_event, ready_events[2]), name="active-probe"),
        asyncio.create_task(processor.main(stop_event, ready_events[3]), name="processor"),
        asyncio.create_task(schedule.main(stop_event, ready_events[4]), name="schedule"),
    ]
    try:
        await _wait_until_ready(services, ready_events)
        _signal_ready()
        logger.info("Power Herald server started")
        done, _ = await asyncio.wait(services, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
    finally:
        stop_event.set()
        pending = [task for task in services if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        _clear_ready()
        logger.info("Power Herald server stopped")


def run() -> None:
    """Synchronous console-script entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()