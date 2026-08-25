# src/outage_periods.py
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerStateChange, OutagePeriod, StateChangeType, Base
from src.config import get_config

config = get_config()
engine = create_engine(config.db_url)
Session = sessionmaker(bind=engine)

def record_outage_transition(session, source_id: int, state: StateChangeType, timestamp):
    if state not in (StateChangeType.ONLINE, StateChangeType.OFFLINE):
        return

    open_period = session.query(OutagePeriod).filter_by(
        source_id=source_id, finished_at=None
    ).order_by(OutagePeriod.started_at.desc()).first()
    if open_period is not None:
        open_period.finished_at = timestamp

    session.add(OutagePeriod(
        source_id=source_id,
        started_at=timestamp,
        state=state
    ))

def update_outage_periods():
    session = Session()
    sources = session.query(PowerSource).all()
    for source in sources:
        state_changes = session.query(PowerStateChange).filter_by(source_id=source.id).order_by(PowerStateChange.timestamp.asc()).all()
        last_period = None
        for sc in state_changes:
            if sc.state == StateChangeType.OFFLINE:
                if not last_period or last_period.finished_at is not None:
                    # Start new outage period
                    last_period = OutagePeriod(
                        source_id=source.id,
                        started_at=sc.timestamp,
                        finished_at=None,
                        state=sc.state
                    )
                    session.add(last_period)
                    session.commit()
            elif sc.state == StateChangeType.ONLINE:
                # Close last outage period if open
                last_period = session.query(OutagePeriod).filter_by(source_id=source.id, finished_at=None).order_by(OutagePeriod.started_at.desc()).first()
                if last_period:
                    last_period.finished_at = sc.timestamp
                    session.commit()
    session.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    update_outage_periods()
    logging.info("Outage periods updated.")
