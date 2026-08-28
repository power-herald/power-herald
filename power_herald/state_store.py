import datetime

from sqlalchemy.orm import Session

from power_herald.models import SourceState, StateChange, StateChangeType
from power_herald.outage_periods import record_outage_transition
from power_herald.config import get_config


def latest_state(session: Session, source_id: int, stable_only=False):
    query = session.query(SourceState).filter_by(source_id=source_id)
    if stable_only:
        query = query.filter(SourceState.state.in_((StateChangeType.ONLINE, StateChangeType.OFFLINE)))
    return query.order_by(SourceState.last_updated_at.desc(), SourceState.id.desc()).first()


def latest_change(session: Session, source_id: int, stable_only=False):
    query = session.query(StateChange).filter_by(source_id=source_id)
    if stable_only:
        query = query.filter(StateChange.state.in_((StateChangeType.ONLINE, StateChangeType.OFFLINE)))
    return query.order_by(StateChange.timestamp.desc(), StateChange.id.desc()).first()


def record_state(
    session: Session,
    source_id: int,
    state: StateChangeType,
    timestamp=None,
):
    timestamp = timestamp or get_config().now()
    previous = latest_state(session, source_id)
    if previous and previous.state == state:
        previous.last_updated_at = timestamp
        return previous, False

    snapshot = SourceState(source_id=source_id, state=state, last_updated_at=timestamp)
    session.add(snapshot)
    return snapshot, True


def record_change(session: Session, source_id: int, state: StateChangeType, timestamp=None):
    timestamp = timestamp or get_config().now()
    if state not in (StateChangeType.ONLINE, StateChangeType.OFFLINE):
        return None

    change = StateChange(source_id=source_id, state=state, timestamp=timestamp)
    session.add(change)
    record_outage_transition(session, source_id, state, timestamp)
    return change