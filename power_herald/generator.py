import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from power_herald.config import get_config
from power_herald.models import PowerSource, PowerSourceType, StateChangeType
from power_herald.notify import notify_state_change
from power_herald.state_store import latest_state, record_change, record_state
import asyncio
import datetime

config = get_config()
logger = logging.getLogger("generator")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)

async def set_generator_state(source_id: int, state: StateChangeType) -> bool:
    """Change a generator state and notify subscribed chats."""
    session = Session()
    source = session.query(PowerSource).filter_by(
        id=source_id, type=PowerSourceType.MANUAL, enabled=True
    ).first()
    if not source:
        session.close()
        return False

    last_state = latest_state(session, source.id, stable_only=True)

    if not last_state or last_state.state != state:
        timestamp = config.now()
        _, changed = record_state(session, source.id, state, timestamp)
        if changed:
            record_change(session, source.id, state, timestamp)
        session.commit()
        logger.warning("Generator %s state changed to %s", source.name, state.value)
        session.close()
        await notify_state_change(source.id, state, timestamp)
        return True
    
    session.close()
    return False
