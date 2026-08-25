# src/probe.py
import asyncio
import logging
import signal
import socket
from urllib.parse import urlsplit
import aiohttp
import sys
from ping3 import ping
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PingMethod, PowerSource, PowerSourceType, PowerStateChange, StateChangeType, Base
import datetime
from src.config import get_config
from src.maintenance import is_maintenance
from src.outage_periods import record_outage_transition

logging.basicConfig(stream=sys.stdout, level=logging.INFO)
config = get_config()
engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)
notification_tasks = set()

async def ping_host(address: str, timeout_sec: int, method: PingMethod = PingMethod.HTTP) -> bool:
    """Check whether an address is reachable using the source's probe method."""
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

        request_timeout = aiohttp.ClientTimeout(total=timeout_sec)
        async with aiohttp.ClientSession() as session:
            async with session.get(address, timeout=request_timeout) as resp:
                return resp.status == 200
    except Exception as e:
        logging.warning(f"Ping failed for {address}: {e}")
        return False

def get_last_state(session, source_id):
    return session.query(PowerStateChange).filter_by(source_id=source_id).order_by(PowerStateChange.timestamp.desc()).first()

def get_last_stable_state(session, source_id):
    return session.query(PowerStateChange).filter(
        PowerStateChange.source_id == source_id,
        PowerStateChange.state.in_([StateChangeType.ONLINE, StateChangeType.OFFLINE])
    ).order_by(PowerStateChange.timestamp.desc()).first()

async def record_passive_state(session, source_id, state, timestamp, notify=False):
    state_change = PowerStateChange(source_id=source_id, state=state, timestamp=timestamp)
    session.add(state_change)
    record_outage_transition(session, source_id, state, timestamp)
    session.commit()
    if notify:
        try:
            from src.notify import notify_state_change
            notification_task = asyncio.create_task(
                notify_state_change(source_id, state, timestamp)
            )
            notification_tasks.add(notification_task)
            notification_task.add_done_callback(notification_tasks.discard)
        except Exception as e:
            logging.warning(f"Notification failed: {e}")

async def probe_passive_sources():
    session = Session()
    try:
        sources = session.query(PowerSource).filter_by(type=PowerSourceType.PASSIVE, enabled=True).all()
        for source in sources:
            maintenance, _ = is_maintenance(source.id)
            if maintenance:
                logging.info(f"Maintenance mode enabled for {source.name}, skipping probe.")
                continue
            last_state = get_last_state(session, source.id)
            stable_state = last_state
            if stable_state is None or stable_state.state == StateChangeType.UNSTABLE:
                stable_state = get_last_stable_state(session, source.id)
            baseline = stable_state.state if stable_state else StateChangeType.OFFLINE
            first_result = None
            results = []

            for _ in range(config.passive_probe_count):
                is_online = await ping_host(
                    source.address, config.passive_probe_timeout, source.ping_method
                )
                result = StateChangeType.ONLINE if is_online else StateChangeType.OFFLINE
                results.append(result)
                if first_result is None:
                    first_result = result
                    if result == baseline:
                        break
                    if result != baseline:
                        await record_passive_state(
                            session, source.id, StateChangeType.UNSTABLE,
                            datetime.datetime.now(datetime.timezone.utc)
                        )
                        logging.info(f"State is UNSTABLE for {source.name}")

            if first_result is None:
                continue
            if first_result != baseline:
                final_state = baseline if baseline in results[1:] else first_result
            else:
                final_state = baseline

            current_state = get_last_state(session, source.id)
            if current_state is None or current_state.state != final_state:
                timestamp = datetime.datetime.now(datetime.timezone.utc)
                should_notify = (
                    final_state != baseline or current_state is None
                ) and final_state != StateChangeType.UNSTABLE
                await record_passive_state(
                    session, source.id, final_state, timestamp, should_notify
                )
                logging.info(f"State changed for {source.name}: {final_state.value}")
    finally:
        session.close()

async def main():
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for shutdown_signal in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(shutdown_signal, stop_event.set)

    try:
        logging.info("Passive probe started")
        while not stop_event.is_set():
            await probe_passive_sources()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=config.passive_probe_interval)
            except asyncio.TimeoutError:
                continue
        logging.info("Shutdown signal received")
    finally:
        if notification_tasks:
            await asyncio.gather(*notification_tasks, return_exceptions=True)
        if "src.notify" in sys.modules:
            await sys.modules["src.notify"].bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
