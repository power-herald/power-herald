from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.config import get_config
from power_herald.models import Emergency

config = get_config()
engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)


def is_emergency() -> bool:
    with Session() as session:
        return session.query(Emergency).filter_by(enabled=True).first() is not None


def set_emergency(enabled, comment=None) -> bool:
    """Apply the mode change; return True if the state actually changed."""
    with Session() as session:
        active = session.query(Emergency).filter_by(enabled=True).all()
        if enabled:
            if active:
                return False
            session.add(Emergency(enabled=True, comment=comment, started_at=config.now()))
        else:
            if not active:
                return False
            for emergency in active:
                emergency.enabled = False
                emergency.ended_at = config.now()
        session.commit()
        return True
