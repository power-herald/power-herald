import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any
import requests

from src.config import get_config

def fetch_outage_data(
    url: str | None = None,
    source: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    config = get_config()
    selected_source = source or config.outage_data_source
    if selected_source == "url":
        response = requests.get(url or config.outage_json_url, timeout=30)
        response.raise_for_status()
        data = response.json()
    elif selected_source == "file":
        path = Path(file_path or config.outage_json_file)
        with path.open(encoding="utf-8") as outage_file:
            data = json.load(outage_file)
    else:
        raise ValueError("source must be either 'url' or 'file'")
    if not isinstance(data, dict):
        raise ValueError("outage data must be a JSON object")
    return data


def content_hash(data: dict[str, Any]) -> str:
    meta = data.get("meta") or {}
    value = meta.get("contentHash") or meta.get("content_hash")
    if isinstance(value, str) and value:
        return value
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def merge_data(preset: dict[str, Any], fact: Any) -> dict[str, Any]:
    result = copy.deepcopy(preset)
    if not isinstance(fact, dict):
        return result
    for gpv_id, weekdays in fact.items():
        if not isinstance(weekdays, dict):
            continue
        target = result.setdefault(gpv_id, {})
        if not isinstance(target, dict):
            result[gpv_id] = target = {}
        for weekday, hours in weekdays.items():
            if isinstance(hours, dict):
                target.setdefault(weekday, {}).update(hours)
    return result


def _periods_for_day(schedule: dict[str, Any], weekday: str) -> list[tuple[str, str, str]]:
    day_data = schedule.get("data", {}).get(weekday, {})
    time_zone = schedule.get("time_zone") or {}
    periods: list[tuple[str, str, str]] = []
    for slot, status in sorted(day_data.items(), key=lambda item: int(item[0])):
        zone = time_zone.get(slot)
        if not zone or len(zone) < 3:
            continue
        start, end = zone[1], zone[2]
        state = "online" if status == "yes" else "offline"
        if status in {"first", "mfirst"}:
            periods.extend([(state, start, f"{start[:3]}30"), ("online", f"{start[:3]}30", end)])
        elif status in {"second", "msecond"}:
            periods.extend([("online", start, f"{start[:3]}30"), (state, f"{start[:3]}30", end)])
        else:
            periods.append((state, start, end))
    grouped: list[tuple[str, str, str]] = []
    for period in periods:
        if grouped and grouped[-1][0] == period[0] and grouped[-1][2] == period[1]:
            grouped[-1] = (period[0], grouped[-1][1], period[2])
        else:
            grouped.append(period)
    return grouped


def prepare_messages(
    data: dict[str, Any], gpvs: list[dict[str, str]], today: dt.date | None = None
) -> dict[str, dict[str, Any]]:
    preset = data.get("preset") or {}
    fact = (data.get("fact") or {}).get("data", {})
    merged = merge_data(preset.get("data") or {}, fact)
    selected_date = today or get_config().now().date()
    weekday = str(selected_date.isoweekday())
    messages: dict[str, dict[str, Any]] = {}
    for gpv in gpvs:
        schedule = {
            "data": {weekday: merged.get(gpv["id"], {}).get(weekday, {})},
            "time_zone": preset.get("time_zone") or {},
        }
        periods = _periods_for_day(schedule, weekday)
        messages[gpv["name"]] = {
            "name": gpv["name"],
            "date": selected_date.isoformat(),
            "outages": [
                {
                    "start": start,
                    "end": end,
                    "status": state,
                }
                for state, start, end in periods
            ],
        }
    return messages


def message_hash(message: dict[str, Any]) -> str:
    encoded = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
