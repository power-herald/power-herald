import datetime

from sqlalchemy.orm import Session

from src.models import PowerState, PowerStateChange, StateChangeType
from src.outage_periods import record_outage_transition


def latest_state(session: Session, source_id: int, stable_only=False):
    query = session.query(PowerState).filter_by(source_id=source_id)
    if stable_only:
        query = query.filter(PowerState.state.in_((StateChangeType.ONLINE, StateChangeType.OFFLINE)))
    return query.order_by(PowerState.last_updated_at.desc(), PowerState.id.desc()).first()


def latest_change(session: Session, source_id: int, stable_only=False):
    query = session.query(PowerStateChange).filter_by(source_id=source_id)
    if stable_only:
        query = query.filter(PowerStateChange.state.in_((StateChangeType.ONLINE, StateChangeType.OFFLINE)))
    return query.order_by(PowerStateChange.timestamp.desc(), PowerStateChange.id.desc()).first()


def record_state(
    session: Session,
    source_id: int,
    state: StateChangeType,
    timestamp=None,
):
    timestamp = timestamp or datetime.datetime.now(datetime.timezone.utc)
    previous = latest_state(session, source_id)
    if previous and previous.state == state:
        previous.last_updated_at = timestamp
        return previous, False

    snapshot = PowerState(source_id=source_id, state=state, last_updated_at=timestamp)
    session.add(snapshot)
    return snapshot, True


def record_change(session: Session, source_id: int, state: StateChangeType, timestamp=None):
    timestamp = timestamp or datetime.datetime.now(datetime.timezone.utc)
    if state not in (StateChangeType.ONLINE, StateChangeType.OFFLINE):
        return None

    change = PowerStateChange(source_id=source_id, state=state, timestamp=timestamp)
    session.add(change)
    record_outage_transition(session, source_id, state, timestamp)
    return change