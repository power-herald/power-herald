"""Run all Power Herald services in one asyncio daemon."""

import asyncio
import logging

from src import active_probe, bot, processor, probe, schedule
from src.lifecycle import create_stop_event

logger = logging.getLogger("server")


async def main() -> None:
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


if __name__ == "__main__":
    asyncio.run(main())