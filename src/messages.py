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


def _escape_markdown_v2(value: str) -> str:
    return value.replace("\\", "\\\\").translate(
        str.maketrans({character: f"\\{character}" for character in "_*[]()~`>#+-=|{}.!"})
    )


def _is_outdated(date: str, end: str, as_of: datetime.datetime) -> bool:
    try:
        period_end = datetime.datetime.fromisoformat(f"{date}T{end}")
    except ValueError:
        return False
    return period_end <= as_of.replace(tzinfo=None)


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
    duration: datetime.timedelta | None = None
) -> str:
    state_key = state.lower()
    message_key = f"notification.source.{state_key}"
    parts = [get_message(message_key, source_name=source_name, state=state.upper())]
    if duration:
        duration_key = f"notification.source.{state_key}_duration"
        parts.append(get_message(duration_key, duration=str(duration).split(".")[0]))
    return "\n".join(parts)


def generator_state_change_message(
    source_name: str,
    state: str,
    duration: datetime.timedelta | None = None,
    maintenance_window: tuple[str, str] | None = None,
    next_working_window: str | None = None,
) -> str:
    state_key = state.lower()
    message_key = f"notification.generator.{state_key}"
    parts = [get_message(message_key, source_name=source_name, state=state.upper())]
    if duration and state_key == "offline":
        duration_key = f"notification.generator.{state_key}_duration"
        parts.append(get_message(duration_key, duration=str(duration).split(".")[0]))
    if maintenance_window:
        parts.append(get_message("notification.generator.maintenance_window", start=maintenance_window[0], end=maintenance_window[1]))
    if next_working_window:
        parts.append(get_message("notification.generator.next_working_window", start=next_working_window))
    return "\n".join(parts)


def group_state_change_message(
    group_name: str,
    group_description: str | None,
    state: str,
    source_durations: list[tuple[str, datetime.timedelta | None]],
) -> str:
    state_key = state.lower()
    message_key = f"notification.group.{state_key}"
    parts = [get_message(message_key, group_name=group_name, state=state.upper())]
    if group_description:
        parts.append(group_description)
    for source_name, duration in source_durations:
        if duration:
            message_key = f"notification.group.source_{state_key}_duration"
            parts.append(get_message(message_key, source_name=source_name, duration=str(duration).split(".")[0]))
        else:
            message_key = f"notification.group.{state_key}_source"
            parts.append(get_message(message_key, source_name=source_name))
    return "\n".join(parts)


def schedule_message(
    date: str,
    outages: list[dict],
    name: str,
    today: bool = True,
    as_of: datetime.datetime | None = None,
) -> str:
    title_key = "schedule.outages_today" if today else "schedule.outages_tomorrow"
    empty_key = "schedule.no_outages_today" if today else "schedule.no_outages_tomorrow"
    as_of = as_of or datetime.datetime.now()
    if not outages:
        return _escape_markdown_v2(get_message(empty_key, date=date, name=name))

    lines = [_escape_markdown_v2(get_message(title_key, date=date, name=name))]
    for outage in outages:
        line = _escape_markdown_v2(
            get_message(
                f"schedule.outage_period_{outage.get('status', 'offline')}",
                start=outage["start"],
                end=outage["end"],
            )
        )
        if _is_outdated(date, outage["end"], as_of):
            line = f"~{line}~"
        lines.append(line)
    return "\n".join(lines)


def schedule_message_from_json(
    message: dict[str, Any], today: bool = True, as_of: datetime.datetime | None = None
) -> str:
    return schedule_message(message["date"], message["outages"], message["name"], today=today, as_of=as_of)