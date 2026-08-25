# src/config.py
import yaml
import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

class Config:
    def __init__(self, config_path: str = "config.yaml"):
        self.config_path = config_path
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
    def db_url(self) -> str:
        db = self.get("database")
        return f"{db['driver']}://{db['user']}:{db['password']}@{db['host']}:{db['port']}/{db['database']}"

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
    def outage_json_url(self) -> str:
        return self.get("outages.json_url")

    @property
    def daily_post_time(self) -> str:
        return self.get("outages.daily_post_time", "07:00")

    @property
    def daily_post_enabled(self) -> bool:
        return self.get("outages.daily_post_enabled", True)

    @property
    def logging_level(self) -> str:
        return self.get("logging.level", "INFO")

    @property
    def buildings(self) -> list:
        return self.get("buildings", [])

# Global config instance
config = None

def load_config(config_path: str = "config.yaml") -> Config:
    global config
    config = Config(config_path)
    return config

def get_config() -> Config:
    global config
    if config is None:
        config = load_config()
    return config
