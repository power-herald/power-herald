import asyncio
import datetime
import logging
import socket
from urllib.parse import urlsplit

import aiohttp
from ping3 import ping
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.config import get_config
from src.maintenance import is_maintenance
from src.models import PowerSource, PowerSourceType, StateChangeType, PingMethod
from src.state_store import record_change, record_state
from src.lifecycle import use_stop_event

config = get_config()
logger = logging.getLogger("passive-prober")

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)


async def ping_host(address: str, timeout_sec: int, method: PingMethod = PingMethod.HTTP) -> bool:
    try:
        if isinstance(method, str):
            method = PingMethod(method.lower())
        if method == PingMethod.PING:
            result = await asyncio.to_thread(ping, address, timeout=timeout_sec)
            return result is not None and result is not False
        if method == PingMethod.TCP:
            endpoint = urlsplit(address if "://" in address else f"//{address}")
            if endpoint.hostname is None or endpoint.port is None:
                raise ValueError("TCP address must include a host and port")
            connection = await asyncio.to_thread(
                socket.create_connection, (endpoint.hostname, endpoint.port), timeout_sec
            )
            with connection:
                return True

        # Default is HTTP GET requests.
        request_timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession() as session:
            async with session.get(address, timeout=request_timeout) as response:
                return response.status == 200
    except Exception as error:
        logger.warning("Ping via %s failed for %s: %s", method.value, address, error)
        return False


async def probe_source(session, source):
    if source.passive is None:
        logger.warning("Passive source %s has no passive configuration", source.name)
        return
    if is_maintenance(source.id)[0]:
        logger.info("Maintenance mode enabled for %s, skipping probe.", source.name)
        return
    states = []
    for _ in range(config.passive_probe_count):
        online = await ping_host(
            source.passive.address, config.passive_probe_timeout, source.passive.ping_method
        )
        states.append(StateChangeType.ONLINE if online else StateChangeType.OFFLINE)
        if len(states) > 1 and states[-1] == states[0]:
            break
    timestamp = get_config().now()
    if len(states) > 1 and states[0] == states[-1]:
        _, changed = record_state(session, source.id, states[-1], timestamp)
        if changed:
            record_change(session, source.id, states[-1], timestamp)
        logger.info("Source %s is %s", source.name, states[-1].value)


async def probe_passive_sources():
    session = Session()
    try:
        sources = session.query(PowerSource).filter(
            PowerSource.type == PowerSourceType.PASSIVE,
            PowerSource.enabled == True,
        ).all()
        await asyncio.gather(*(probe_source(session, source) for source in sources))
        session.commit()
    finally:
        session.close()


async def main(stop_event=None):
    stop_event = use_stop_event(stop_event)
    logger.info("Passive probe started")
    try:
        while not stop_event.is_set():
            await probe_passive_sources()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=config.passive_probe_interval)
            except asyncio.TimeoutError:
                pass
        logger.info("Shutdown signal received")
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())