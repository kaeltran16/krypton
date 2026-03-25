import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


_YAML_SECTION_PREFIX = {
    "collector": "collector_",
    "engine": "engine_",
    "api": "api_",
    "onchain": "onchain_",
    "news": "news_",
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
    # auth
    google_client_id: str = ""
    jwt_secret: str = "change-me-in-production"
    allowed_emails: str = ""  # comma-separated
    cors_origin: str = ""  # comma-separated origins

    # secrets (from .env)
    openrouter_api_key: str
    openrouter_model: str = "anthropic/claude-3.5-sonnet"
    database_url: str = "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton"
    redis_url: str = "redis://localhost:6379/0"

    # okx private api
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""
    okx_demo: bool = True

    # pairs and timeframes
    pairs: list[str] = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    timeframes: list[str] = ["15m", "1h", "4h", "1D"]

    # collector
    collector_mode: Literal["event_driven", "scheduled"] = "event_driven"
    collector_polling_interval_seconds: int = 900
    collector_rest_poll_interval_seconds: int = 300

    # engine
    engine_signal_threshold: int = 40
    engine_llm_threshold: int = 40
    engine_llm_timeout_seconds: int = 30
    engine_traditional_weight: float = 0.40
    engine_flow_weight: float = 0.22
    engine_onchain_weight: float = 0.23
    engine_pattern_weight: float = 0.15
    engine_confluence_max_score: int = 15

    # on-chain data
    onchain_enabled: bool = True
    onchain_poll_interval_seconds: int = 300
    onchain_tier2_poll_interval_seconds: int = 1800
    cryptoquant_api_key: str = ""

    # news
    news_poll_interval_seconds: int = 150
    news_llm_context_window_minutes: int = 30
    news_high_impact_push_enabled: bool = True
    news_llm_daily_budget: int = 200
    news_relevance_keywords: list[str] = [
        "interest rate", "Fed", "CPI", "inflation", "sanctions",
        "war", "tariff", "regulation", "crypto ban", "SEC",
    ]
    news_rss_feeds: list[dict] = []
    cryptopanic_api_key: str = ""
    news_api_key: str = ""

    # ML model
    ml_enabled: bool = True
    ml_confidence_threshold: float = 0.65
    ml_checkpoint_dir: str = "models"

    # unified ML blending
    engine_ml_weight: float = 0.25
    ml_sl_min_atr: float = 1.0
    ml_sl_max_atr: float = 3.5
    ml_tp1_min_atr: float = 1.0
    ml_tp2_max_atr: float = 8.0
    ml_rr_floor: float = 1.0

    # LLM factor scoring
    llm_factor_weights: dict[str, float] = Field(default_factory=lambda: {
        "support_proximity": 6.0, "resistance_proximity": 6.0,
        "level_breakout": 8.0, "htf_alignment": 7.0,
        "rsi_divergence": 7.0, "volume_divergence": 6.0,
        "macd_divergence": 6.0, "volume_exhaustion": 5.0,
        "funding_extreme": 5.0, "crowded_positioning": 5.0,
        "pattern_confirmation": 5.0, "news_catalyst": 7.0,
    })
    llm_factor_total_cap: float = 35.0

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
                    if hasattr(self, key) and key.upper() not in os.environ:
                        object.__setattr__(self, key, value)
