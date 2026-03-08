"""Unit tests for PositionSizer and compute_rr_ratios."""

from app.engine.risk import PositionSizer, compute_rr_ratios


class TestPositionSizer:
    def test_basic_calculation(self):
        # Wide SL so 25% equity cap doesn't interfere
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(
            entry=100, stop_loss=90,
            take_profit_1=120, take_profit_2=140,
        )
        assert result is not None
        # risk_amount = 10000 * 0.01 = 100
        # sl_distance = |100 - 90| / 100 = 0.1
        # position_size_usd = 100 / 0.1 = 1000 (< 2500 cap)
        assert result["risk_amount_usd"] == 100.0
        assert result["position_size_usd"] == 1000.0
        assert result["position_size_base"] == 10.0  # 1000/100
        assert result["risk_pct"] == 1.0
        # tp1_rr = |120-100| / |100-90| = 2.0
        assert result["tp1_rr"] == 2.0
        # tp2_rr = |140-100| / |100-90| = 4.0
        assert result["tp2_rr"] == 4.0

    def test_max_position_size_cap(self):
        sizer = PositionSizer(equity=100000, risk_per_trade=0.02, max_position_size_usd=5000)
        result = sizer.calculate(entry=50000, stop_loss=49500)
        # Without cap: risk_amount=2000, sl_dist=0.01, pos=200000 -> capped to 5000
        assert result is not None
        assert result["position_size_usd"] == 5000.0

    def test_equity_cap_25_percent(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.10)
        result = sizer.calculate(entry=50000, stop_loss=49900)
        # risk_amount=1000, sl_dist=0.002, pos=500000 -> capped at 25% of 10000 = 2500
        assert result is not None
        assert result["position_size_usd"] == 2500.0

    def test_lot_size_rounding(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(
            entry=100, stop_loss=90, lot_size=1.0,
        )
        assert result is not None
        # pos_usd=1000, pos_base=10.0, lot=1.0 -> 10.0 already aligned
        assert result["position_size_base"] == 10.0

    def test_lot_size_rounds_down(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(
            entry=100, stop_loss=90, lot_size=3.0,
        )
        assert result is not None
        # pos_base=10.0, 10/3=3.33 -> floor=3, 3*3=9.0
        assert result["position_size_base"] == 9.0

    def test_min_order_size_rejection(self):
        sizer = PositionSizer(equity=100, risk_per_trade=0.01)
        result = sizer.calculate(
            entry=50000, stop_loss=49000, min_order_size=0.01,
        )
        # risk_amount=1, pos_usd=50, pos_base=0.001 < 0.01 -> rejected
        assert result is None

    def test_zero_stop_loss_distance(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(entry=50000, stop_loss=50000)
        assert result is None

    def test_zero_entry(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(entry=0, stop_loss=49000)
        assert result is None

    def test_zero_equity(self):
        sizer = PositionSizer(equity=0, risk_per_trade=0.01)
        result = sizer.calculate(entry=50000, stop_loss=49000)
        assert result is None

    def test_negative_equity(self):
        sizer = PositionSizer(equity=-1000, risk_per_trade=0.01)
        result = sizer.calculate(entry=50000, stop_loss=49000)
        assert result is None

    def test_no_take_profits(self):
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(entry=50000, stop_loss=49000)
        assert result is not None
        assert result["tp1_rr"] is None
        assert result["tp2_rr"] is None

    def test_short_direction_rr(self):
        """Short: entry below stop loss."""
        sizer = PositionSizer(equity=10000, risk_per_trade=0.01)
        result = sizer.calculate(
            entry=50000, stop_loss=51000,
            take_profit_1=48000, take_profit_2=46000,
        )
        assert result is not None
        # sl_dist = |50000-51000| / 50000 = 0.02
        assert result["tp1_rr"] == 2.0  # |48000-50000|/|50000-51000| = 2
        assert result["tp2_rr"] == 4.0


class TestComputeRRRatios:
    def test_basic(self):
        result = compute_rr_ratios(50000, 49000, 52000, 54000)
        assert result["tp1_rr"] == 2.0
        assert result["tp2_rr"] == 4.0

    def test_zero_sl_distance(self):
        result = compute_rr_ratios(50000, 50000, 52000, 54000)
        assert result["tp1_rr"] is None
        assert result["tp2_rr"] is None

    def test_no_tp(self):
        result = compute_rr_ratios(50000, 49000, None, None)
        assert result["tp1_rr"] is None
        assert result["tp2_rr"] is None
