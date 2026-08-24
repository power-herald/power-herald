# src/probe.py
import asyncio
import logging
import aiohttp
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerSourceType, PowerStateChange, StateChangeType, Base
import datetime

# Placeholder DB URL, replace with config
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

async def ping_host(address: str, timeout: int = 2) -> bool:
    """Ping a host using HTTP GET. Returns True if reachable."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(address, timeout=timeout) as resp:
                return resp.status == 200
    except Exception as e:
        logging.warning(f"Ping failed for {address}: {e}")
        return False

def get_last_state(session, source_id):
    return session.query(PowerStateChange).filter_by(source_id=source_id).order_by(PowerStateChange.timestamp.desc()).first()

async def probe_passive_sources():
    session = Session()
    sources = session.query(PowerSource).filter_by(type=PowerSourceType.PASSIVE, enabled=True).all()
    for source in sources:
        from src.maintenance import is_maintenance
        maintenance, _ = is_maintenance(source.id)
        if maintenance:
            logging.info(f"Maintenance mode enabled for {source.name}, skipping probe.")
            continue
        is_online = await ping_host(source.address)
        last_state = get_last_state(session, source.id)
        new_state = StateChangeType.ONLINE if is_online else StateChangeType.OFFLINE
        if not last_state or last_state.state != new_state:
            state_change = PowerStateChange(source_id=source.id, state=new_state, timestamp=datetime.datetime.utcnow())
            session.add(state_change)
            session.commit()
            logging.info(f"State changed for {source.name}: {new_state.value}")
            try:
                import asyncio
                from src.notify import notify_state_change
                asyncio.create_task(notify_state_change(state_change))
            except Exception as e:
                logging.warning(f"Notification failed: {e}")
    session.close()

async def main():
    while True:
        await probe_passive_sources()
        await asyncio.sleep(30)  # Probe interval (configurable)

if __name__ == "__main__":
    asyncio.run(main())
