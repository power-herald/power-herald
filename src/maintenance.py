# src/maintenance.py
from sqlalchemy.orm import sessionmaker
from sqlalchemy import create_engine
from src.models import MaintenanceMode, PowerSource, Base
import os

# Placeholder DB URL, replace with config
DB_URL = "mysql+pymysql://user:password@localhost/power_herald"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

def is_maintenance(source_id=None):
    session = Session()
    # Check global maintenance
    global_mode = session.query(MaintenanceMode).filter_by(source_id=None, enabled=True).first()
    if global_mode:
        session.close()
        return True, global_mode.comment
    # Check per-source maintenance
    if source_id is not None:
        source_mode = session.query(MaintenanceMode).filter_by(source_id=source_id, enabled=True).first()
        if source_mode:
            session.close()
            return True, source_mode.comment
    session.close()
    return False, None

def set_maintenance(enabled, source_id=None, comment=None):
    session = Session()
    if enabled:
        mode = MaintenanceMode(source_id=source_id, enabled=True, comment=comment)
        session.add(mode)
    else:
        q = session.query(MaintenanceMode).filter_by(source_id=source_id, enabled=True)
        for m in q:
            m.enabled = False
    session.commit()
    session.close()
