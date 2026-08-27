"""Command-line administration client for the Power Herald database."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from src.models import (
    Base,
    Chat,
    GeneratorSource,
    MaintenanceMode,
    Period,
    PassiveSource,
    PingMethod,
    PowerSource,
    PowerGroupSource,
    PowerGroup,
    PowerSourceType,
    SourceState,
    StateChange,
    StateChangeType,
    Subscription,
)


ENTITY_MODELS = {
    "groups": PowerGroup,
    "sources": PowerSource,
    "group-sources": PowerGroupSource,
    "subscriptions": Subscription,
    "chats": Chat,
    "maintenances": MaintenanceMode,
}


def parse_datetime(value: str) -> dt.datetime:
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("use an ISO-8601 datetime") from error


def enum_value(enum_type: type, value: str) -> Any:
    try:
        return enum_type[value.upper()]
    except KeyError as error:
        choices = ", ".join(member.name.lower() for member in enum_type)
        raise argparse.ArgumentTypeError(f"must be one of: {choices}") from error


def add_common_id(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", type=int)


def add_entity_commands(subparsers: Any, name: str, fields: dict[str, dict[str, Any]]) -> None:
    entity = subparsers.add_parser(name, help=f"manage {name}")
    actions = entity.add_subparsers(dest="action", required=True)

    add = actions.add_parser("add")
    for field, options in fields.items():
        add.add_argument(f"--{field.replace('_', '-')}", required=options.get("required", False), type=options.get("type", str))

    list_parser = actions.add_parser("list")
    list_parser.add_argument("--json", action="store_true")

    update = actions.add_parser("update")
    add_common_id(update)
    for field, options in fields.items():
        update.add_argument(f"--{field.replace('_', '-')}", type=options.get("type", str))

    remove = actions.add_parser("remove")
    add_common_id(remove)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ph-cli", description="Manage Power Herald database records")
    parser.add_argument("--config", default="config.yaml", help="configuration file")
    parser.add_argument("--db-url", help="SQLAlchemy database URL, overriding config.yaml")
    commands = parser.add_subparsers(dest="command", required=True)

    database = commands.add_parser("db", help="database operations")
    database.add_subparsers(dest="action", required=True).add_parser("restore", help="create all tables from the model schema")

    add_entity_commands(commands, "groups", {
        "name": {"required": True}, "description": {},
    })
    add_entity_commands(commands, "sources", {
        "name": {"required": True}, "type": {"required": True, "type": lambda value: enum_value(PowerSourceType, value)},
        "address": {}, "ping_method": {"type": lambda value: enum_value(PingMethod, value)},
        "enabled": {"type": int}, "is_generator": {"type": int}, "description": {}, "work_duration_minutes": {"type": int},
        "maintenance_duration_minutes": {"type": int},
    })
    add_entity_commands(commands, "group-sources", {
        "group_id": {"required": True, "type": int},
        "source_id": {"required": True, "type": int},
    })
    add_entity_commands(commands, "subscriptions", {
        "chat_id": {"required": True, "type": int}, "source_id": {"required": True, "type": int},
        "enabled": {"type": int},
    })
    add_entity_commands(commands, "chats", {
        "chat_id": {"required": True}, "title": {}, "thread_id": {"type": int},
        "enabled": {"type": int}, "is_private": {"type": int}, "source_id": {"type": int},
    })
    add_entity_commands(commands, "maintenances", {
        "source_id": {"type": int}, "enabled": {"type": int}, "comment": {},
    })

    for name, model in (("power-states", SourceState), ("state-changes", StateChange), ("outage-periods", Period)):
        listing = commands.add_parser(name, help=f"list {name}")
        listing.add_argument("--source-id", type=int)
        if model in (SourceState, StateChange, Period):
            listing.add_argument("--state", type=lambda value: enum_value(StateChangeType, value))
        listing.add_argument("--from", dest="from_time", type=parse_datetime)
        listing.add_argument("--to", dest="to_time", type=parse_datetime)
        listing.add_argument("--json", action="store_true")

    return parser


def serialize(record: Any) -> dict[str, Any]:
    result = {}
    for column in record.__table__.columns:
        value = getattr(record, column.name)
        if isinstance(value, (dt.datetime, dt.date)):
            value = value.isoformat()
        elif hasattr(value, "name"):
            value = value.name.lower()
        result[column.name] = value
    if isinstance(record, PowerSource):
        passive = record.passive
        generator = record.generator
        result.update({
            "address": None if passive is None else passive.address,
            "ping_method": None if passive is None else passive.ping_method.name.lower(),
            "work_duration_minutes": None if generator is None else generator.work_duration_minutes,
            "maintenance_duration_minutes": None if generator is None else generator.maintenance_duration_minutes,
        })
    return result


def json_text(value: Any) -> str:
    encoding = (sys.stdout.encoding or "").lower().replace("-", "")
    return json.dumps(value, default=str, ensure_ascii=encoding != "utf8", indent=2)


def output(records: list[Any], as_json: bool) -> None:
    data = [serialize(record) for record in records]
    if as_json:
        print(json_text(data))
        return
    if not data:
        print("No records found.")
        return
    columns = list(data[0])
    print("\t".join(columns))
    for row in data:
        print("\t".join("" if row[column] is None else str(row[column]) for column in columns))


def apply_values(record: Any, arguments: argparse.Namespace) -> None:
    for column in record.__table__.columns:
        if column.name == "id":
            continue
        value = getattr(arguments, column.name, None)
        if value is not None:
            if column.name in {"enabled", "is_private", "is_generator"}:
                value = bool(value)
            setattr(record, column.name, value)


def apply_source_type_values(source: PowerSource, arguments: argparse.Namespace) -> None:
    if source.type == PowerSourceType.PASSIVE:
        source.generator = None
        subtype = source.passive
        fields = ("address", "ping_method")
        subtype_model = PassiveSource
    elif source.type == PowerSourceType.MANUAL and source.is_generator:
        source.passive = None
        subtype = source.generator
        fields = ("work_duration_minutes", "maintenance_duration_minutes")
        subtype_model = GeneratorSource
    else:
        source.passive = None
        source.generator = None
        return

    values = {field: getattr(arguments, field, None) for field in fields}
    if subtype is None and any(value is not None for value in values.values()):
        subtype = subtype_model()
        if source.type == PowerSourceType.PASSIVE:
            source.passive = subtype
        else:
            source.generator = subtype
    if subtype is not None:
        for field, value in values.items():
            if value is not None:
                setattr(subtype, field, value)


def list_history(session: Session, model: Any, arguments: argparse.Namespace) -> list[Any]:
    query = session.query(model)
    if arguments.source_id is not None:
        query = query.filter(model.source_id == arguments.source_id)
    if arguments.state is not None:
        query = query.filter(model.state == arguments.state)
    time_column = {SourceState: SourceState.last_updated_at, StateChange: StateChange.timestamp,
                   Period: Period.started_at}[model]
    if arguments.from_time is not None:
        query = query.filter(time_column >= arguments.from_time)
    if arguments.to_time is not None:
        query = query.filter(time_column <= arguments.to_time)
    return query.order_by(time_column.desc(), model.id.desc()).all()


def run(arguments: argparse.Namespace) -> int:
    db_url = arguments.db_url
    if db_url is None:
        from src.config import Config

        db_url = Config(arguments.config).db_url
    engine = create_engine(db_url)
    session_factory = sessionmaker(bind=engine)
    if arguments.command == "db":
        Base.metadata.create_all(engine)
        print("Database restored.")
        return 0

    with session_factory() as session:
        if arguments.command in ENTITY_MODELS:
            model = ENTITY_MODELS[arguments.command]
            if arguments.action == "list":
                output(session.query(model).order_by(model.id).all(), arguments.json)
            elif arguments.action == "add":
                record = model()
                apply_values(record, arguments)
                if model is PowerSource:
                    apply_source_type_values(record, arguments)
                session.add(record)
                session.commit()
                print(json_text(serialize(record)))
            elif arguments.action == "update":
                record = session.get(model, arguments.id)
                if record is None:
                    raise ValueError(f"{arguments.command} record {arguments.id} was not found")
                apply_values(record, arguments)
                if model is PowerSource:
                    apply_source_type_values(record, arguments)
                session.commit()
                print(json_text(serialize(record)))
            else:
                record = session.get(model, arguments.id)
                if record is None:
                    raise ValueError(f"{arguments.command} record {arguments.id} was not found")
                session.delete(record)
                session.commit()
                print(f"Removed {arguments.command} record {arguments.id}.")
        else:
            model = {"power-states": SourceState, "state-changes": StateChange,
                     "outage-periods": Period}[arguments.command]
            output(list_history(session, model, arguments), arguments.json)
    return 0


def main() -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args())
    except (IntegrityError, ValueError) as error:
        print(f"ph-cli: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())