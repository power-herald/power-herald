import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from power_herald.config import get_config
from power_herald.messages import get_message
from power_herald.models import Chat, Emergency

config = get_config()
engine = create_engine(config.db_url, **config.db_engine_options)
Session = sessionmaker(bind=engine)
logger = logging.getLogger("emergency")


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


async def broadcast_emergency(bot, enabled: bool, comment: str | None = None) -> None:
    text = get_message(f"notification.emergency.{'enabled' if enabled else 'disabled'}")
    if enabled and comment:
        text = f"{text}\n{get_message('notification.emergency.comment', comment=comment)}"
    with Session() as session:
        chats = session.query(Chat).filter_by(enabled=True).all()
        for chat in chats:
            try:
                await bot.send_message(chat.chat_id, text, message_thread_id=chat.thread_id)
            except Exception:
                logger.exception("Failed to send emergency notification to %s", chat.chat_id)
