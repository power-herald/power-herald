# src/outage_periods.py
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, StateChange, Period, StateChangeType
from src.config import get_config

config = get_config()
logger = logging.getLogger("outage")

engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

def record_outage_transition(session, source_id: int, state: StateChangeType, timestamp):
    if state not in (StateChangeType.ONLINE, StateChangeType.OFFLINE):
        return

    existing_period = session.query(Period).filter_by(
        source_id=source_id, started_at=timestamp, state=state
    ).first()
    if existing_period is not None:
        return

    open_period = session.query(Period).filter_by(
        source_id=source_id, finished_at=None
    ).order_by(Period.started_at.desc()).first()
    if open_period is not None:
        open_period.finished_at = timestamp

    session.add(Period(
        source_id=source_id,
        started_at=timestamp,
        state=state
    ))

def update_outage_periods():
    session = Session()
    sources = session.query(PowerSource).all()
    for source in sources:
        state_changes = session.query(StateChange).filter_by(source_id=source.id).order_by(StateChange.timestamp.asc()).all()
        for sc in state_changes:
            record_outage_transition(session, source.id, sc.state, sc.timestamp)
        session.commit()
    session.close()

if __name__ == "__main__":
    update_outage_periods()
    logger.info("Outage periods updated.")
