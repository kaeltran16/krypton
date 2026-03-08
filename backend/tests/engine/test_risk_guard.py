"""Unit tests for RiskGuard."""

from datetime import datetime, timedelta, timezone

from app.engine.risk import RiskGuard


def _default_settings(**overrides):
    settings = {
        "daily_loss_limit_pct": 0.03,
        "max_concurrent_positions": 3,
        "max_exposure_pct": 1.5,
        "cooldown_after_loss_minutes": None,
        "max_risk_per_trade_pct": 0.02,
    }
    settings.update(overrides)
    return settings


class TestRiskGuard:
    def test_all_ok(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=0.01, open_positions_count=1,
            total_exposure_usd=5000,
        )
        assert result["status"] == "OK"
        assert all(r["status"] == "OK" for r in result["rules"])

    def test_daily_loss_blocked(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=-0.035, open_positions_count=0,
            total_exposure_usd=0,
        )
        assert result["status"] == "BLOCKED"
        daily_rule = next(r for r in result["rules"] if r["rule"] == "daily_loss_limit")
        assert daily_rule["status"] == "BLOCKED"

    def test_daily_loss_at_limit(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=-0.03, open_positions_count=0,
            total_exposure_usd=0,
        )
        assert result["status"] == "BLOCKED"

    def test_max_concurrent_blocked(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=0.0, open_positions_count=3,
            total_exposure_usd=5000,
        )
        assert result["status"] == "BLOCKED"
        concurrent_rule = next(r for r in result["rules"] if r["rule"] == "max_concurrent")
        assert concurrent_rule["status"] == "BLOCKED"

    def test_max_exposure_blocked(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=6000,
            daily_pnl_pct=0.0, open_positions_count=0,
            total_exposure_usd=10000,
        )
        assert result["status"] == "BLOCKED"
        exposure_rule = next(r for r in result["rules"] if r["rule"] == "max_exposure")
        assert exposure_rule["status"] == "BLOCKED"

    def test_cooldown_warning(self):
        guard = RiskGuard(_default_settings(cooldown_after_loss_minutes=30))
        recent_sl = datetime.now(timezone.utc) - timedelta(minutes=10)
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=0.0, open_positions_count=0,
            total_exposure_usd=0, last_sl_hit_at=recent_sl,
        )
        assert result["status"] == "WARNING"
        cooldown_rule = next(r for r in result["rules"] if r["rule"] == "cooldown")
        assert cooldown_rule["status"] == "WARNING"

    def test_cooldown_elapsed(self):
        guard = RiskGuard(_default_settings(cooldown_after_loss_minutes=30))
        old_sl = datetime.now(timezone.utc) - timedelta(minutes=60)
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=0.0, open_positions_count=0,
            total_exposure_usd=0, last_sl_hit_at=old_sl,
        )
        assert result["status"] == "OK"

    def test_cooldown_disabled(self):
        guard = RiskGuard(_default_settings(cooldown_after_loss_minutes=None))
        result = guard.check(
            equity=10000, size_usd=100,
            daily_pnl_pct=0.0, open_positions_count=0,
            total_exposure_usd=0,
            last_sl_hit_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        # No cooldown rule should be emitted
        assert not any(r["rule"] == "cooldown" for r in result["rules"])

    def test_max_risk_per_trade_warning(self):
        guard = RiskGuard(_default_settings())
        result = guard.check(
            equity=10000, size_usd=300,  # 3% > 2% limit
            daily_pnl_pct=0.0, open_positions_count=0,
            total_exposure_usd=0,
        )
        assert result["status"] == "WARNING"
        risk_rule = next(r for r in result["rules"] if r["rule"] == "max_risk_per_trade")
        assert risk_rule["status"] == "WARNING"

    def test_mixed_blocked_and_warning(self):
        guard = RiskGuard(_default_settings(cooldown_after_loss_minutes=30))
        result = guard.check(
            equity=10000, size_usd=300,
            daily_pnl_pct=-0.04, open_positions_count=0,
            total_exposure_usd=0,
            last_sl_hit_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        # BLOCKED takes priority over WARNING
        assert result["status"] == "BLOCKED"
