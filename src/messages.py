import datetime
import os
from pathlib import Path
from typing import Any

import yaml


LOCALE_PATH = Path(__file__).resolve().parent.parent / "locale.yaml"


def _load_locale() -> dict[str, Any]:
    locale_path = Path(os.getenv("LOCALE_PATH", LOCALE_PATH))
    with locale_path.open("r", encoding="utf-8") as locale_file:
        return yaml.safe_load(locale_file) or {}


_locale = _load_locale()


def create_message(key: str, **parts: Any) -> str:
    """Create a complete localized message from a locale key and its pieces."""
    value: Any = _locale
    for part in key.split("."):
        if not isinstance(value, dict) or part not in value:
            raise KeyError(f"Message not found: {key}")
        value = value[part]
    if not isinstance(value, str):
        raise TypeError(f"Message is not a string: {key}")
    return value.format(**parts)


get_message = create_message


def bot_greeting(chat_id: int, thread_id: int | None) -> str:
    return get_message("bot.greeting", chat_id=chat_id, thread_id=thread_id)


def state_change_message(
    source_name: str,
    state: str,
    duration: datetime.timedelta | None = None,
    maintenance_window: tuple[str, str] | None = None,
    next_working_window: str | None = None,
) -> str:
    state_key = state.lower()
    message_key = f"notification.{state_key}" if state_key in {"online", "offline"} else "notification.state"
    parts = [get_message(message_key, source_name=source_name, state=state.upper())]
    if duration:
        duration_key = f"notification.{state_key}_duration" if state_key in {"online", "offline"} else "notification.previous_period"
        parts.append(get_message(duration_key, duration=str(duration).split(".")[0]))
    if maintenance_window:
        parts.append(get_message("notification.maintenance_window", start=maintenance_window[0], end=maintenance_window[1]))
    if next_working_window:
        parts.append(get_message("notification.next_working_window", start=next_working_window))
    return "\n".join(parts)


def schedule_message(date: str, outages: list[dict]) -> str:
    if not outages:
        return get_message("schedule.no_outages", date=date)
    return "\n".join(
        [get_message("schedule.outages", date=date)]
        + [get_message("schedule.outage_period", start=outage["start"], end=outage["end"]) for outage in outages]
    )