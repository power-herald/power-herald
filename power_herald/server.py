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
    services = [
        asyncio.create_task(bot.main(stop_event), name="bot"),
        asyncio.create_task(probe.main(stop_event), name="passive-probe"),
        asyncio.create_task(active_probe.main(stop_event), name="active-probe"),
        asyncio.create_task(processor.main(stop_event), name="processor"),
        asyncio.create_task(schedule.main(stop_event), name="schedule"),
    ]
    logger.info("Power Herald server started")
    try:
        done, _ = await asyncio.wait(services, return_when=asyncio.FIRST_EXCEPTION)
        for task in done:
            task.result()
    finally:
        stop_event.set()
        pending = [task for task in services if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        logger.info("Power Herald server stopped")


def run() -> None:
    """Synchronous console-script entry point."""
    asyncio.run(main())


if __name__ == "__main__":
    run()