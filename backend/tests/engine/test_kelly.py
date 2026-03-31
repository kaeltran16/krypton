import pytest

from app.engine.risk import compute_kelly_risk


def _make_outcomes(wins: int, losses: int, win_pnl: float = 1.0, loss_pnl: float = -1.0):
    """Build a list of outcome dicts for testing."""
    outcomes = []
    for _ in range(wins):
        outcomes.append({"outcome": "TP1_HIT", "outcome_pnl_pct": win_pnl})
    for _ in range(losses):
        outcomes.append({"outcome": "SL_HIT", "outcome_pnl_pct": loss_pnl})
    return outcomes


class TestComputeKellyRisk:
    def test_insufficient_history_returns_default(self):
        outcomes = _make_outcomes(10, 10)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01
        assert result["sample_size"] == 20

    def test_empty_outcomes_returns_default(self):
        result = compute_kelly_risk([])
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01
        assert result["sample_size"] == 0

    def test_barely_profitable_in_range(self):
        # 26W/24L at ±1% → win_rate=0.52, odds=1.0
        # kelly = 0.52 - 0.48/1.0 = 0.04, fractional = 0.04*0.35 = 0.014
        outcomes = _make_outcomes(26, 24)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == pytest.approx(0.014, abs=0.001)
        assert result["win_rate"] == pytest.approx(0.52)
        assert result["odds"] == pytest.approx(1.0)
        assert result["sample_size"] == 50

    def test_strong_performance_hits_ceiling(self):
        # 40W/10L at ±1% → win_rate=0.80, odds=1.0
        # kelly = 0.80 - 0.20/1.0 = 0.60, fractional = 0.21 → clamped to 0.02
        outcomes = _make_outcomes(40, 10)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.02  # ceiling

    def test_losing_strategy_hits_floor(self):
        # 15W/35L at ±1% → win_rate=0.30, odds=1.0
        # kelly = 0.30 - 0.70/1.0 = -0.40, fractional = -0.14 → clamped to 0.005
        outcomes = _make_outcomes(15, 35)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.005  # floor

    def test_all_wins_returns_ceiling(self):
        outcomes = _make_outcomes(50, 0)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.02

    def test_all_losses_returns_floor(self):
        outcomes = _make_outcomes(0, 50)
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["risk_per_trade"] == 0.005

    def test_all_breakeven_returns_default(self):
        outcomes = [{"outcome": "TP1_HIT", "outcome_pnl_pct": 0.0} for _ in range(50)]
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "default"
        assert result["risk_per_trade"] == 0.01

    def test_filters_terminal_outcomes_only(self):
        outcomes = _make_outcomes(26, 24)
        # Add non-terminal outcomes that should be ignored
        outcomes.append({"outcome": "PENDING", "outcome_pnl_pct": 0.0})
        outcomes.append({"outcome": "EXPIRED", "outcome_pnl_pct": 0.0})
        result = compute_kelly_risk(outcomes)
        assert result["sample_size"] == 50  # PENDING and EXPIRED excluded

    def test_new_outcome_types_counted(self):
        # TP1_TRAIL and TP1_TP2 are wins
        outcomes = [
            {"outcome": "TP1_TRAIL", "outcome_pnl_pct": 1.5} for _ in range(26)
        ] + [
            {"outcome": "TP1_TP2", "outcome_pnl_pct": 2.0} for _ in range(4)
        ] + [
            {"outcome": "SL_HIT", "outcome_pnl_pct": -1.0} for _ in range(20)
        ]
        result = compute_kelly_risk(outcomes)
        assert result["source"] == "kelly"
        assert result["win_rate"] == pytest.approx(0.60)

    def test_custom_parameters(self):
        outcomes = _make_outcomes(10, 10)  # only 20
        result = compute_kelly_risk(
            outcomes, min_signals=10, floor=0.003, ceiling=0.05, default_risk=0.02
        )
        assert result["source"] == "kelly"  # 20 >= min_signals=10
        assert result["risk_per_trade"] >= 0.003
        assert result["risk_per_trade"] <= 0.05
