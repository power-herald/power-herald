# power_herald/config.py
import yaml
import os
import datetime as dt
import logging
import sys
from typing import Dict, Any
from dotenv import load_dotenv
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

load_dotenv()

DEFAULT_CONFIG_PATH = os.environ.get("POWER_HERALD_CONFIG", "./config.yaml")

class Config:
    def __init__(self, config_path: str | None = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self.data = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f) or {}

    def get(self, key: str, default=None) -> Any:
        keys = key.split(".")
        value = self.data
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
        return value if value is not None else default

    @property
    def bot_token(self) -> str:
        return os.getenv("BOT_TOKEN") or self.get("telegram.token")

    @property
    def webhook_url(self) -> str:
        return os.getenv("WEBHOOK_URL") or self.get("telegram.webhook_url")

    @property
    def webhook_secret(self) -> str:
        return os.getenv("WEBHOOK_SECRET") or self.get("telegram.webhook_secret")

    @property
    def webhook_path(self) -> str:
        return self.get("telegram.webhook_path", "/webhook")

    @property
    def webhook_address(self) -> str:
        return self.get("telegram.webhook_address", "0.0.0.0")

    @property
    def webhook_port(self) -> int:
        return self.get("telegram.webhook_port", 8080)

    @property
    def db_driver(self) -> str:
        driver = self.get("database.driver", "sqlite")
        if driver not in {"sqlite", "mysql+pymysql"}:
            raise ValueError("database.driver must be either 'sqlite' or 'mysql+pymysql'")
        return driver

    @property
    def db_engine_options(self) -> dict[str, dict[str, bool]]:
        if self.db_driver == "sqlite":
            return {"connect_args": {"check_same_thread": False}}
        return {}

    @property
    def db_url(self) -> str:
        db = self.get("database", {})
        if self.db_driver == "sqlite":
            database = db.get("database", "./power_herald.db")
            if not isinstance(database, str) or not database:
                raise ValueError("database.database must be a non-empty SQLite database path")
            return f"sqlite:///{database}"

        return (
            f"{self.db_driver}://{db['user']}:{db['password']}"
            f"@{db['host']}:{db['port']}/{db['database']}"
        )

    @property
    def timezone(self) -> ZoneInfo:
        value = self.get("timezone", "Europe/Kyiv")
        if not isinstance(value, str) or not value:
            raise ValueError("timezone must be a valid IANA timezone name")
        try:
            return ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise ValueError(f"Unknown timezone: {value}") from error

    def now(self) -> dt.datetime:
        return dt.datetime.now(self.timezone)

    @property
    def locale_file(self) -> str:
        locale_file = self.get("locale_file", "locale.yaml")
        if os.path.isabs(locale_file):
            return locale_file
        return os.path.join(os.path.dirname(os.path.abspath(self.config_path)), locale_file)

    @property
    def admin_chat_ids(self) -> list:
        ids = os.getenv("ADMIN_CHAT_IDS")
        if ids:
            ids = [id.strip() for id in ids.split(",")]
        else:
            ids = self.get("admin.chat_ids", [])
        return [str(i) for i in ids]

    @property
    def passive_probe_enabled(self) -> bool:
        return self.get("probing.passive.enabled", True)

    @property
    def passive_probe_interval(self) -> int:
        return self.get("probing.passive.interval_seconds", 30)

    @property
    def passive_probe_timeout(self) -> int:
        return self.get("probing.passive.timeout_seconds", 2)

    @property
    def passive_probe_count(self) -> int:
        count = self.get("probing.passive.probe_count", 3)
        if not isinstance(count, int) or count < 1:
            raise ValueError("probing.passive.probe_count must be a positive integer")
        return count

    @property
    def active_probe_enabled(self) -> bool:
        return self.get("probing.active.enabled", True)

    @property
    def active_probe_port(self) -> int:
        return self.get("probing.active.port", 8081)

    @property
    def active_probe_address(self) -> str:
        return self.get("probing.active.address", "0.0.0.0")

    @property
    def active_probe_endpoint(self) -> str:
        return self.get("probing.active.endpoint", "/ping")

    @property
    def active_probe_timeout(self) -> int:
        return self.get("probing.active.timeout_seconds", self.passive_probe_interval)

    @property
    def state_processor_interval(self) -> int:
        return self.get("probing.processor.interval_seconds", self.passive_probe_interval)

    @property
    def outage_json_url(self) -> str:
        return self.get("outages.json_url")

    @property
    def outage_data_source(self) -> str:
        source = self.get("outages.source", "url")
        if source not in {"url", "file"}:
            raise ValueError("outages.source must be either 'url' or 'file'")
        return source

    @property
    def outage_json_file(self) -> str:
        return self.get("outages.json_file")

    @property
    def outage_update_interval_seconds(self) -> int:
        value = self.get("outages.delay_seconds", 1800)
        if not isinstance(value, int) or value <= 0:
            raise ValueError("outages.delay_seconds must be a positive integer")
        return value

    @property
    def outage_schedule_send_time_tomorrow(self) -> dt.time | None:
        value = self.get("outages.schedule_send_time.tomorrow")
        if (isinstance(value, str) and value == "" ) or (isinstance(value, bool) and not value):
            return None
        if not isinstance(value, str):
            raise ValueError("outages.schedule_send_time.tomorrow must be in HH:MM format")
        try:
            return dt.datetime.strptime(value, "%H:%M").time()
        except ValueError as error:
            raise ValueError("outages.schedule_send_time.tomorrow must be in HH:MM format") from error

    @property
    def outage_schedule_send_time_today(self) -> dt.time | None:
        value = self.get("outages.schedule_send_time.today")
        if (isinstance(value, str) and value == "" ) or (isinstance(value, bool) and not value):
            return None
        if not isinstance(value, str):
            raise ValueError("outages.schedule_send_time.today must be in HH:MM format")
        try:
            return dt.datetime.strptime(value, "%H:%M").time()
        except ValueError as error:
            raise ValueError("outages.schedule_send_time.today must be in HH:MM format") from error

    @property
    def gpvs(self) -> list[dict[str, str]]:
        value = self.get("outages.gpvs", [])
        if not isinstance(value, list):
            raise ValueError("outages.gpvs must be a list")
        for gpv in value:
            if not isinstance(gpv, dict) or not isinstance(gpv.get("name"), str) or not isinstance(gpv.get("id"), str):
                raise ValueError("each outages.gpvs item must have string name and id")
        return value

    @property
    def logging_level(self) -> str:
        return self.get("logging.level", "INFO")

    @property
    def logging_format(self) -> str:
        return self.get("logging.format", "%(asctime)s [%(name)s] [%(levelname)s] %(message)s")


def configure_logging(settings: Config) -> None:
    level = getattr(logging, settings.logging_level.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"Invalid logging level: {settings.logging_level}")
    logging.basicConfig(
        stream=sys.stdout,
        level=level,
        format=settings.logging_format,
    )

# Global config instance
config = None

def load_config(config_path: str | None = None) -> Config:
    global config
    config = Config(config_path)
    configure_logging(config)
    return config

def get_config() -> Config:
    global config
    if config is None:
        config = load_config()
    return config
