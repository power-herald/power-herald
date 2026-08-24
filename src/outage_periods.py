# src/outage_periods.py
import logging
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import PowerSource, PowerStateChange, OutagePeriod, StateChangeType, Base
import datetime

# Placeholder DB URL, replace with config
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

def update_outage_periods():
    session = Session()
    sources = session.query(PowerSource).all()
    for source in sources:
        state_changes = session.query(PowerStateChange).filter_by(source_id=source.id).order_by(PowerStateChange.timestamp.asc()).all()
        last_period = None
        for sc in state_changes:
            if sc.state in [StateChangeType.OFFLINE, StateChangeType.UNSTABLE]:
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
