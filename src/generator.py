import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.config import get_config
from src.models import PowerSource, PowerSourceType, StateChangeType
from src.notify import notify_state_change
from src.state_store import latest_state, record_change, record_state
import asyncio
import datetime

config = get_config()
logger = logging.getLogger("generator")
logging.getLogger("aiohttp.access").setLevel(logging.WARNING)

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

async def set_generator_state(source_id: int, state: StateChangeType) -> bool:
    """Change a generator state and notify subscribed chats."""
    session = Session()
    source = session.query(PowerSource).filter_by(
        id=source_id, type=PowerSourceType.GENERATOR, enabled=True
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
        logger.info("Generator %s state changed to %s", source.name, state.value)
        session.close()
        await notify_state_change(source.id, state, timestamp)
        return True
    
    session.close()
    return False
