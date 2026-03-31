"""Position sizing engine and risk guard for trade risk management."""

import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculates recommended position size based on account equity and risk parameters."""

    def __init__(
        self,
        equity: float,
        risk_per_trade: float = 0.01,
        max_position_size_usd: float | None = None,
    ):
        self.equity = equity
        self.risk_per_trade = risk_per_trade
        self.max_position_size_usd = max_position_size_usd

    def calculate(
        self,
        entry: float,
        stop_loss: float,
        take_profit_1: float | None = None,
        take_profit_2: float | None = None,
        lot_size: float | None = None,
        min_order_size: float | None = None,
    ) -> dict:
        """Calculate position size and risk/reward metrics.

        Returns dict with position_size_usd, position_size_base, risk_amount_usd,
        risk_pct, tp1_rr, tp2_rr. Returns None if inputs are invalid.
        """
        if entry <= 0 or stop_loss <= 0:
            return None
        if self.equity <= 0:
            return None

        sl_distance = abs(entry - stop_loss) / entry
        if sl_distance == 0:
            return None

        risk_amount = self.equity * self.risk_per_trade
        position_size_usd = risk_amount / sl_distance

        # Safety caps
        if self.max_position_size_usd and position_size_usd > self.max_position_size_usd:
            position_size_usd = self.max_position_size_usd

        # Cap at 25% of equity
        max_equity_cap = self.equity * 0.25
        if position_size_usd > max_equity_cap:
            position_size_usd = max_equity_cap

        position_size_base = position_size_usd / entry

        # Round down to lot size if provided
        if lot_size and lot_size > 0:
            position_size_base = math.floor(position_size_base / lot_size) * lot_size
            position_size_usd = position_size_base * entry

        # Enforce minimum order size
        if min_order_size and position_size_base < min_order_size:
            return None

        # R:R ratios
        tp1_rr = None
        tp2_rr = None
        sl_dist_abs = abs(entry - stop_loss)
        if sl_dist_abs > 0:
            if take_profit_1:
                tp1_rr = round(abs(take_profit_1 - entry) / sl_dist_abs, 2)
            if take_profit_2:
                tp2_rr = round(abs(take_profit_2 - entry) / sl_dist_abs, 2)

        return {
            "position_size_usd": round(position_size_usd, 2),
            "position_size_base": round(position_size_base, 8),
            "risk_amount_usd": round(risk_amount, 2),
            "risk_pct": round(self.risk_per_trade * 100, 2),
            "tp1_rr": tp1_rr,
            "tp2_rr": tp2_rr,
        }


def compute_rr_ratios(
    entry: float, stop_loss: float,
    take_profit_1: float | None, take_profit_2: float | None,
) -> dict:
    """Compute R:R ratios without needing equity or OKX. Used as fallback."""
    sl_dist = abs(entry - stop_loss)
    if sl_dist == 0:
        return {"tp1_rr": None, "tp2_rr": None}
    tp1_rr = round(abs(take_profit_1 - entry) / sl_dist, 2) if take_profit_1 else None
    tp2_rr = round(abs(take_profit_2 - entry) / sl_dist, 2) if take_profit_2 else None
    return {"tp1_rr": tp1_rr, "tp2_rr": tp2_rr}


TERMINAL_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "SL_HIT", "TP1_TRAIL", "TP1_TP2"})
WIN_OUTCOMES = frozenset({"TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"})


def compute_kelly_risk(
    recent_outcomes: list[dict],
    kelly_fraction: float = 0.35,
    min_signals: int = 50,
    default_risk: float = 0.01,
    floor: float = 0.005,
    ceiling: float = 0.02,
) -> dict:
    """Compute adaptive risk_per_trade using fractional Kelly criterion.

    Returns dict with risk_per_trade, kelly_raw, win_rate, odds, sample_size, source.
    """
    terminal = [o for o in recent_outcomes if o["outcome"] in TERMINAL_OUTCOMES]
    n = len(terminal)

    if n < min_signals:
        return {
            "risk_per_trade": default_risk,
            "kelly_raw": 0.0,
            "win_rate": 0.0,
            "odds": 0.0,
            "sample_size": n,
            "source": "default",
        }

    wins = [o for o in terminal if o["outcome"] in WIN_OUTCOMES]
    win_rate = len(wins) / n

    pos_pnls = [o["outcome_pnl_pct"] for o in terminal if o["outcome_pnl_pct"] > 0]
    neg_pnls = [abs(o["outcome_pnl_pct"]) for o in terminal if o["outcome_pnl_pct"] < 0]

    avg_win = sum(pos_pnls) / len(pos_pnls) if pos_pnls else 0.0
    avg_loss = sum(neg_pnls) / len(neg_pnls) if neg_pnls else 0.0

    if avg_win == 0.0 and avg_loss == 0.0:
        return {
            "risk_per_trade": default_risk,
            "kelly_raw": 0.0,
            "win_rate": win_rate,
            "odds": 0.0,
            "sample_size": n,
            "source": "default",
        }
    if avg_loss == 0.0:
        return {
            "risk_per_trade": ceiling,
            "kelly_raw": 1.0,
            "win_rate": win_rate,
            "odds": float("inf"),
            "sample_size": n,
            "source": "kelly",
        }
    if avg_win == 0.0:
        return {
            "risk_per_trade": floor,
            "kelly_raw": -1.0,
            "win_rate": win_rate,
            "odds": 0.0,
            "sample_size": n,
            "source": "kelly",
        }

    odds = avg_win / avg_loss
    kelly_raw = win_rate - (1 - win_rate) / odds
    kelly_frac = kelly_raw * kelly_fraction
    risk = max(floor, min(ceiling, kelly_frac))

    return {
        "risk_per_trade": round(risk, 6),
        "kelly_raw": round(kelly_raw, 6),
        "win_rate": round(win_rate, 4),
        "odds": round(odds, 4),
        "sample_size": n,
        "source": "kelly",
    }


def compute_correlation_factor(
    new_pair: str,
    new_direction: str,
    open_positions: list[dict],
    returns_by_pair: dict[str, list[float]],
    lookback: int = 20,
    dampening_floor: float = 0.4,
) -> dict:
    """Compute position size dampening based on correlation with open positions.

    Args:
        new_pair: Pair of the new signal (e.g. "BTC-USDT-SWAP").
        new_direction: "LONG" or "SHORT".
        open_positions: List of dicts with "pair" and "direction" keys.
        returns_by_pair: Per-pair list of recent candle-over-candle returns.
            Keys are pair strings, values are lists of float returns.
        lookback: Number of candles for rolling correlation.
        dampening_floor: Minimum multiplier (0.4 = 60% max reduction).

    Returns:
        Dict with "factor" (float 0.4-1.0), "max_correlation" (float),
        and "correlated_pair" (str or None).
    """
    if not open_positions or new_pair not in returns_by_pair:
        return {"factor": 1.0, "max_correlation": 0.0, "correlated_pair": None}

    new_returns = returns_by_pair[new_pair]
    if len(new_returns) < lookback:
        return {"factor": 1.0, "max_correlation": 0.0, "correlated_pair": None}

    max_corr = 0.0
    correlated_pair = None

    for pos in open_positions:
        if pos["direction"] != new_direction:
            continue
        pos_pair = pos["pair"]
        if pos_pair == new_pair or pos_pair not in returns_by_pair:
            continue

        pos_returns = returns_by_pair[pos_pair]
        if len(pos_returns) < lookback:
            continue

        corr = _pearson(new_returns[-lookback:], pos_returns[-lookback:])
        if abs(corr) > max_corr:
            max_corr = abs(corr)
            correlated_pair = pos_pair

    # Linear dampening: 1.0 at corr=0, dampening_floor at corr=1.0
    factor = max(dampening_floor, 1.0 - max_corr * (1.0 - dampening_floor))

    return {
        "factor": round(factor, 4),
        "max_correlation": round(max_corr, 4),
        "correlated_pair": correlated_pair,
    }


def _pearson(x: list[float], y: list[float]) -> float:
    """Compute Pearson correlation between two equal-length lists."""
    n = len(x)
    if n < 2:
        return 0.0
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    cov = sum((xi - mean_x) * (yi - mean_y) for xi, yi in zip(x, y))
    var_x = sum((xi - mean_x) ** 2 for xi in x)
    var_y = sum((yi - mean_y) ** 2 for yi in y)
    denom = math.sqrt(var_x * var_y)
    if denom == 0:
        return 0.0
    return cov / denom


class RiskGuard:
    """Evaluates whether a trade should be allowed based on configurable risk rules."""

    def __init__(self, settings: dict):
        self.daily_loss_limit_pct = settings.get("daily_loss_limit_pct", 0.03)
        self.max_concurrent_positions = settings.get("max_concurrent_positions", 3)
        self.max_exposure_pct = settings.get("max_exposure_pct", 1.5)
        self.cooldown_after_loss_minutes = settings.get("cooldown_after_loss_minutes")
        self.max_risk_per_trade_pct = settings.get("max_risk_per_trade_pct", 0.02)

    def check(
        self,
        equity: float,
        size_usd: float,
        daily_pnl_pct: float,
        open_positions_count: int,
        total_exposure_usd: float,
        last_sl_hit_at: datetime | None = None,
    ) -> dict:
        """Run all risk rules and return aggregate result.

        Returns:
            {
                "status": "OK" | "WARNING" | "BLOCKED",
                "rules": [{"rule": str, "status": str, "reason": str}, ...]
            }
        """
        rules = []

        # 1. Daily loss limit
        if daily_pnl_pct <= -self.daily_loss_limit_pct:
            rules.append({
                "rule": "daily_loss_limit",
                "status": "BLOCKED",
                "reason": f"Daily loss {daily_pnl_pct*100:.1f}% exceeds -{self.daily_loss_limit_pct*100:.1f}% limit",
            })
        else:
            remaining = self.daily_loss_limit_pct + daily_pnl_pct
            rules.append({
                "rule": "daily_loss_limit",
                "status": "OK",
                "reason": f"Daily P&L {daily_pnl_pct*100:+.1f}%, {remaining*100:.1f}% remaining",
            })

        # 2. Max concurrent positions
        if open_positions_count >= self.max_concurrent_positions:
            rules.append({
                "rule": "max_concurrent",
                "status": "BLOCKED",
                "reason": f"{open_positions_count}/{self.max_concurrent_positions} positions open",
            })
        else:
            rules.append({
                "rule": "max_concurrent",
                "status": "OK",
                "reason": f"{open_positions_count}/{self.max_concurrent_positions} positions open",
            })

        # 3. Max exposure
        new_exposure = total_exposure_usd + size_usd
        exposure_pct = new_exposure / equity if equity > 0 else 0
        if exposure_pct > self.max_exposure_pct:
            rules.append({
                "rule": "max_exposure",
                "status": "BLOCKED",
                "reason": f"Exposure {exposure_pct*100:.0f}% would exceed {self.max_exposure_pct*100:.0f}% limit",
            })
        else:
            rules.append({
                "rule": "max_exposure",
                "status": "OK",
                "reason": f"Exposure {exposure_pct*100:.0f}% within {self.max_exposure_pct*100:.0f}% limit",
            })

        # 4. Cooldown after loss
        if self.cooldown_after_loss_minutes and last_sl_hit_at:
            elapsed = (datetime.now(timezone.utc) - last_sl_hit_at).total_seconds() / 60
            if elapsed < self.cooldown_after_loss_minutes:
                remaining_mins = int(self.cooldown_after_loss_minutes - elapsed)
                rules.append({
                    "rule": "cooldown",
                    "status": "WARNING",
                    "reason": f"Cooldown active, {remaining_mins}min remaining after last SL hit",
                })
            else:
                rules.append({
                    "rule": "cooldown",
                    "status": "OK",
                    "reason": "Cooldown period elapsed",
                })

        # 5. Max risk per trade
        if equity > 0:
            trade_risk_pct = size_usd / equity
            if trade_risk_pct > self.max_risk_per_trade_pct:
                rules.append({
                    "rule": "max_risk_per_trade",
                    "status": "WARNING",
                    "reason": f"Trade size {trade_risk_pct*100:.1f}% of equity exceeds {self.max_risk_per_trade_pct*100:.1f}% limit",
                })
            else:
                rules.append({
                    "rule": "max_risk_per_trade",
                    "status": "OK",
                    "reason": f"Trade size {trade_risk_pct*100:.1f}% within {self.max_risk_per_trade_pct*100:.1f}% limit",
                })

        # Aggregate status
        statuses = [r["status"] for r in rules]
        if "BLOCKED" in statuses:
            overall = "BLOCKED"
        elif "WARNING" in statuses:
            overall = "WARNING"
        else:
            overall = "OK"

        return {"status": overall, "rules": rules}
