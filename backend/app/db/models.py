import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Candle(Base):
    __tablename__ = "candles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", "timestamp", name="uq_candle"),
    )


class Signal(Base):
    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    final_score: Mapped[int] = mapped_column(Integer, nullable=False)
    traditional_score: Mapped[int] = mapped_column(Integer, nullable=False)
    llm_opinion: Mapped[str | None] = mapped_column(String(16))
    llm_confidence: Mapped[str | None] = mapped_column(String(8))
    explanation: Mapped[str | None] = mapped_column(Text)
    entry: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    stop_loss: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit_1: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    take_profit_2: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    raw_indicators: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # outcome tracking
    outcome: Mapped[str] = mapped_column(
        String(16), default="PENDING", server_default="PENDING", nullable=False
    )
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_pnl_pct: Mapped[float | None] = mapped_column(Numeric(10, 4))
    outcome_duration_minutes: Mapped[int | None] = mapped_column(Integer)
    # journal fields
    user_note: Mapped[str | None] = mapped_column(String(500))
    user_status: Mapped[str] = mapped_column(
        String(16), default="OBSERVED", server_default="OBSERVED", nullable=False
    )
    # risk metrics (position sizing data, nullable)
    risk_metrics: Mapped[dict | None] = mapped_column(JSONB)
    # detected candlestick/chart patterns
    detected_patterns: Mapped[list | None] = mapped_column(JSONB)
    # news correlation
    correlated_news_ids: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_signal_pair_tf_created", "pair", "timeframe", "created_at"),
    )


class RiskSettings(Base):
    __tablename__ = "risk_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    risk_per_trade: Mapped[float] = mapped_column(Float, default=0.01)
    max_position_size_usd: Mapped[float | None] = mapped_column(Float)
    daily_loss_limit_pct: Mapped[float] = mapped_column(Float, default=0.03)
    max_concurrent_positions: Mapped[int] = mapped_column(Integer, default=3)
    max_exposure_pct: Mapped[float] = mapped_column(Float, default=1.5)
    cooldown_after_loss_minutes: Mapped[int | None] = mapped_column(Integer)
    max_risk_per_trade_pct: Mapped[float] = mapped_column(Float, default=0.02)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_risk_settings_singleton"),
    )


class NewsEvent(Base):
    __tablename__ = "news_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    headline: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(16), nullable=False)
    impact: Mapped[str | None] = mapped_column(String(16))
    sentiment: Mapped[str | None] = mapped_column(String(16))
    affected_pairs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    llm_summary: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("url", name="uq_news_url"),
        UniqueConstraint("fingerprint", name="uq_news_fingerprint"),
        Index("ix_news_impact_published", "impact", "published_at"),
    )


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh_key: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pairs: Mapped[list] = mapped_column(JSONB, nullable=False)
    timeframes: Mapped[list] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class PipelineSettings(Base):
    __tablename__ = "pipeline_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pairs: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    )
    timeframes: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=["15m", "1h", "4h"]
    )
    signal_threshold: Mapped[int] = mapped_column(Integer, nullable=False, default=40)
    onchain_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    news_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    news_context_window: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_pipeline_settings_singleton"),
    )


class OrderFlowSnapshot(Base):
    __tablename__ = "order_flow_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    funding_rate: Mapped[float | None] = mapped_column(Float)
    open_interest: Mapped[float | None] = mapped_column(Float)
    oi_change_pct: Mapped[float | None] = mapped_column(Float)
    long_short_ratio: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (
        Index("ix_oflow_pair_ts", "pair", "timestamp"),
    )


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    status: Mapped[str] = mapped_column(
        String(16), default="running", server_default="running", nullable=False
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    pairs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    date_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    date_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    results: Mapped[dict | None] = mapped_column(JSONB)


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # price, signal, indicator, portfolio
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    pair: Mapped[str | None] = mapped_column(String(32))
    timeframe: Mapped[str | None] = mapped_column(String(8))
    condition: Mapped[str | None] = mapped_column(String(32))  # crosses_above, crosses_below, pct_move, gt, lt
    threshold: Mapped[float | None] = mapped_column(Float)
    secondary_threshold: Mapped[float | None] = mapped_column(Float)  # pct_move window in minutes
    filters: Mapped[dict | None] = mapped_column(JSONB)  # signal type filters
    peak_value: Mapped[float | None] = mapped_column(Float)  # portfolio drawdown peak
    urgency: Mapped[str] = mapped_column(String(16), nullable=False, default="normal")  # critical, normal, silent
    cooldown_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_one_shot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        Index("ix_alert_type_active", "type", "is_active"),
    )


class AlertHistory(Base):
    __tablename__ = "alert_history"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    alert_id: Mapped[str] = mapped_column(UUID(as_uuid=False), ForeignKey("alerts.id", ondelete="CASCADE"), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    trigger_value: Mapped[float] = mapped_column(Float, nullable=False)
    delivery_status: Mapped[str] = mapped_column(String(32), nullable=False)  # delivered, failed, silenced_by_cooldown, silenced_by_quiet_hours

    __table_args__ = (
        Index("ix_alert_history_alert_triggered", "alert_id", "triggered_at"),
    )


class AlertSettings(Base):
    __tablename__ = "alert_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    quiet_hours_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quiet_hours_start: Mapped[str] = mapped_column(String(5), nullable=False, default="22:00")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), nullable=False, default="08:00")
    quiet_hours_tz: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    __table_args__ = (
        CheckConstraint("id = 1", name="ck_alert_settings_singleton"),
    )


class PerformanceTrackerRow(Base):
    __tablename__ = "performance_tracker"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    current_sl_atr: Mapped[float] = mapped_column(Float, nullable=False, default=1.5)
    current_tp1_atr: Mapped[float] = mapped_column(Float, nullable=False, default=2.0)
    current_tp2_atr: Mapped[float] = mapped_column(Float, nullable=False, default=3.0)
    last_optimized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_optimized_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    __table_args__ = (
        UniqueConstraint("pair", "timeframe", name="uq_tracker_pair_timeframe"),
    )
