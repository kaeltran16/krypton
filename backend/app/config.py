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
    openrouter_model: str = "qwen/qwen3.5-plus-02-15"
    database_url: str = "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton"
    redis_url: str = "redis://localhost:6379/0"
    agent_api_key: str = ""

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
    engine_confluence_level_weight_1: float = 0.50
    engine_confluence_level_weight_2: float = 0.30
    engine_confluence_trend_alignment_steepness: float = 0.30
    engine_confluence_adx_strength_center: float = 15.0
    engine_confluence_adx_conviction_ratio: float = 0.60
    engine_confluence_mr_penalty_factor: float = 0.50
    engine_mr_llm_trigger: float = 0.30

    # execution parameters (optimizer-tunable)
    engine_kelly_fraction: float = 0.35
    engine_partial_fraction: float = 0.50
    engine_trail_atr_multiplier: float = 1.0

    # liquidation scoring
    engine_liquidation_weight: float = 0.0
    engine_liquidation_cluster_max_score: float = 30.0
    engine_liquidation_asymmetry_max_score: float = 25.0
    engine_liquidation_cluster_weight: float = 0.6
    engine_liquidation_proximity_steepness: float = 2.0
    engine_liquidation_decay_half_life_hours: float = 4.0
    engine_liquidation_asymmetry_steepness: float = 3.0

    # cross-pair correlation dampener
    engine_correlation_dampening_floor: float = 0.4

    # anti-whipsaw cooldown
    engine_cooldown_max_candles: int = 3

    atr_optimizer_mode: Literal["gp", "sweep"] = "gp"
    ic_prune_threshold: float = -0.05
    ic_reenable_threshold: float = 0.0
    ew_ic_lookback_days: int = 90

    # on-chain data
    onchain_enabled: bool = True
    onchain_poll_interval_seconds: int = 300
    onchain_tier2_poll_interval_seconds: int = 1800
    cryptoquant_api_key: str = ""

    # news
    news_poll_interval_seconds: int = 150
    news_llm_context_window_minutes: int = 30
    news_high_impact_push_enabled: bool = True
    news_relevance_keywords: list[str] = [
        "interest rate", "Fed", "CPI", "inflation", "sanctions",
        "war", "tariff", "regulation", "crypto ban", "SEC",
    ]
    news_rss_feeds: list[dict] = []
    cryptopanic_api_key: str = ""
    news_api_key: str = ""

    # ML model
    ml_enabled: bool = True
    ml_confidence_threshold: float = 0.40
    ml_checkpoint_dir: str = "models"

    # MinIO model storage
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: str = ""
    minio_bucket: str = "krypton-models"
    minio_use_ssl: bool = False
    minio_archive_retention_count: int = 5
    minio_archive_retention_days: int = 30

    # conviction floor (min scale applied to low-conviction sources)
    engine_conviction_floor: float = 0.3

    # unified ML blending (adaptive weight ramp)
    engine_ml_weight_min: float = 0.20
    engine_ml_weight_max: float = 0.50
    ensemble_disagreement_scale: float = 8.0
    ensemble_stale_fresh_days: float = 7.0
    ensemble_stale_decay_days: float = 21.0
    ensemble_stale_floor: float = 0.3
    ensemble_confidence_cap_partial: float = 0.5
    drift_psi_moderate: float = 0.1
    drift_psi_severe: float = 0.25
    drift_penalty_moderate: float = 0.3
    drift_penalty_severe: float = 0.6
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
    llm_factor_total_cap: float = 25.0
    engine_calibration_window: int = 30
    engine_calibration_floor: float = 0.5

    # slippage modeling (replay-only)
    # override via env var SLIPPAGE_BASE_BPS or top-level key in config.yaml
    # (not nested under engine — YAML flattening does not handle dict values)
    slippage_base_bps: dict[str, float] = Field(default_factory=lambda: {
        "BTC-USDT-SWAP": 3,
        "ETH-USDT-SWAP": 5,
        "WIF-USDT-SWAP": 12,
    })

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
