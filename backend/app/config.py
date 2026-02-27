from pathlib import Path
from typing import Literal

import yaml
from pydantic_settings import BaseSettings


_YAML_SECTION_PREFIX = {
    "collector": "collector_",
    "engine": "engine_",
    "api": "api_",
}


def load_yaml_config(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _flatten_yaml(config: dict) -> dict:
    flat = {}
    for key, value in config.items():
        prefix = _YAML_SECTION_PREFIX.get(key)
        if prefix and isinstance(value, dict):
            for sub_key, sub_value in value.items():
                flat[f"{prefix}{sub_key}"] = sub_value
        else:
            flat[key] = value
    return flat


class Settings(BaseSettings):
    # secrets (from .env)
    krypton_api_key: str
    openrouter_api_key: str
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    database_url: str = "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton"
    redis_url: str = "redis://localhost:6379/0"

    # pairs and timeframes
    pairs: list[str] = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    timeframes: list[str] = ["15m", "1h", "4h"]

    # collector
    collector_mode: Literal["event_driven", "scheduled"] = "event_driven"
    collector_polling_interval_seconds: int = 900
    collector_rest_poll_interval_seconds: int = 300

    # engine
    engine_signal_threshold: int = 50
    engine_llm_threshold: int = 30
    engine_llm_timeout_seconds: int = 30
    engine_traditional_weight: float = 0.60
    engine_llm_weight: float = 0.40

    # push notifications
    vapid_private_key: str = ""
    vapid_claims_email: str = ""
    vapid_public_key: str = ""

    # api
    api_ws_heartbeat_seconds: int = 30

    # config file path
    krypton_config_path: str | None = None

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    def model_post_init(self, __context) -> None:
        if self.krypton_config_path:
            path = Path(self.krypton_config_path)
            if path.exists():
                yaml_config = load_yaml_config(path)
                flat = _flatten_yaml(yaml_config)
                for key, value in flat.items():
                    if hasattr(self, key):
                        object.__setattr__(self, key, value)
