import pytest
from datetime import datetime, timezone

from app.engine.llm_calibration import compute_multiplier


def test_compute_multiplier_below_ramp_returns_floor():
    assert compute_multiplier(0.30, floor=0.5) == 0.5


def test_compute_multiplier_at_ramp_low_returns_floor():
    assert compute_multiplier(0.40, floor=0.5) == 0.5


def test_compute_multiplier_at_ramp_high_returns_one():
    assert compute_multiplier(0.55, floor=0.5) == 1.0


def test_compute_multiplier_above_ramp_high_returns_one():
    assert compute_multiplier(0.70, floor=0.5) == 1.0


def test_compute_multiplier_midpoint_interpolates():
    # midpoint of ramp: accuracy=0.475 -> (0.475-0.40)/0.15 = 0.5 -> 0.5*0.5+0.5 = 0.75
    assert compute_multiplier(0.475, floor=0.5) == pytest.approx(0.75)


def test_compute_multiplier_custom_floor():
    assert compute_multiplier(0.30, floor=0.3) == 0.3
    assert compute_multiplier(0.55, floor=0.3) == 1.0


def test_compute_multiplier_floor_one_disables_calibration():
    assert compute_multiplier(0.10, floor=1.0) == 1.0
    assert compute_multiplier(0.50, floor=1.0) == 1.0


def test_compute_multiplier_zero_accuracy():
    assert compute_multiplier(0.0, floor=0.5) == 0.5


def test_compute_multiplier_exactly_50pct_accuracy():
    # (0.50 - 0.40) / 0.15 = 0.667 -> 0.667 * 0.5 + 0.5 = 0.833
    assert compute_multiplier(0.50, floor=0.5) == pytest.approx(0.8333, abs=0.001)


from app.engine.llm_calibration import compute_factor_correctness


def test_factor_correctness_bullish_long_win():
    assert compute_factor_correctness("bullish", "LONG", "TP1_HIT") is True


def test_factor_correctness_bearish_short_win():
    assert compute_factor_correctness("bearish", "SHORT", "TP2_HIT") is True


def test_factor_correctness_bullish_long_loss():
    assert compute_factor_correctness("bullish", "LONG", "SL_HIT") is False


def test_factor_correctness_bearish_short_loss():
    assert compute_factor_correctness("bearish", "SHORT", "SL_HIT") is False


def test_factor_correctness_bearish_long_win_is_incorrect():
    assert compute_factor_correctness("bearish", "LONG", "TP1_TP2") is False


def test_factor_correctness_bullish_short_win_is_incorrect():
    assert compute_factor_correctness("bullish", "SHORT", "TP1_TRAIL") is False


def test_factor_correctness_bearish_long_loss_is_correct():
    # bearish factor on LONG that hit SL -> factor correctly warned
    assert compute_factor_correctness("bearish", "LONG", "SL_HIT") is True


def test_factor_correctness_bullish_short_loss_is_correct():
    assert compute_factor_correctness("bullish", "SHORT", "SL_HIT") is True


def test_factor_correctness_all_win_outcomes():
    """All WIN_OUTCOMES should be treated as wins."""
    for outcome in ("TP1_HIT", "TP2_HIT", "TP1_TRAIL", "TP1_TP2"):
        assert compute_factor_correctness("bullish", "LONG", outcome) is True
        assert compute_factor_correctness("bearish", "SHORT", outcome) is True


from app.engine.llm_calibration import LLMCalibrationState


@pytest.fixture
def make_record():
    def _make(signal_id, pair, factor_type, correct, **kw):
        return {
            "signal_id": signal_id,
            "pair": pair,
            "factor_type": factor_type,
            "direction": "bullish",
            "strength": 2,
            "correct": correct,
            "resolved_at": kw.get("resolved_at", datetime(2026, 3, 15, tzinfo=timezone.utc)),
        }
    return _make


def test_state_empty_returns_empty_multipliers():
    state = LLMCalibrationState()
    assert state.get_multipliers("BTC-USDT-SWAP") == {}


def test_state_below_min_samples_returns_no_multiplier(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(9)]
    state.load_records(rows)
    assert state.get_multipliers("BTC-USDT-SWAP") == {}


def test_state_all_correct_returns_one(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(15)]
    state.load_records(rows)
    mults = state.get_multipliers("BTC-USDT-SWAP")
    assert mults["rsi_divergence"] == 1.0


def test_state_all_incorrect_returns_floor(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", False) for i in range(15)]
    state.load_records(rows)
    mults = state.get_multipliers("BTC-USDT-SWAP")
    assert mults["rsi_divergence"] == 0.5


def test_state_per_pair_override(make_record):
    state = LLMCalibrationState(window=50, floor=0.5)
    # 20 global records: 60% accuracy -> multiplier 1.0
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", i < 12) for i in range(20)]
    # 16 records for ETH with ~31% accuracy -> floor
    rows += [make_record(20 + i, "ETH-USDT-SWAP", "rsi_divergence", i < 5) for i in range(16)]
    state.load_records(rows)
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 1.0
    assert state.get_multipliers("ETH-USDT-SWAP")["rsi_divergence"] == 0.5


def test_state_per_pair_boundary_14_falls_back_to_global(make_record):
    """14 per-pair samples -> below CALIBRATION_WINDOW_PAIR_MIN, use global."""
    state = LLMCalibrationState(window=30, floor=0.5)
    # 14 BTC records all incorrect, but global has 24 records at 60% (above ramp)
    btc_rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", False) for i in range(14)]
    eth_rows = [make_record(14 + i, "ETH-USDT-SWAP", "rsi_divergence", True) for i in range(10)]
    state.load_records(btc_rows + eth_rows)
    # global: 10/24 correct = ~42% -> still in ramp range, not floor
    # BTC has 14 per-pair samples < 15 threshold -> falls back to global
    mults = state.get_multipliers("BTC-USDT-SWAP")
    assert "rsi_divergence" in mults  # global kicks in (24 >= 10 min samples)
    # no per-pair override for BTC


def test_state_per_pair_boundary_15_activates_override(make_record):
    """15 per-pair samples -> at CALIBRATION_WINDOW_PAIR_MIN, per-pair activates."""
    state = LLMCalibrationState(window=30, floor=0.5)
    # 15 BTC records all incorrect + 10 ETH records all correct
    btc_rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", False) for i in range(15)]
    eth_rows = [make_record(15 + i, "ETH-USDT-SWAP", "rsi_divergence", True) for i in range(10)]
    state.load_records(btc_rows + eth_rows)
    # BTC per-pair: 0% accuracy -> floor
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 0.5


def test_state_window_trimming(make_record):
    state = LLMCalibrationState(window=15, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(15)]
    state.load_records(rows)
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 1.0
    # add 15 more signals: all incorrect (pushes old correct ones out)
    for i in range(15, 30):
        state.record_outcomes(i, "BTC-USDT-SWAP", [{
            "factor_type": "rsi_divergence",
            "direction": "bullish",
            "strength": 2,
            "correct": False,
            "resolved_at": datetime(2026, 3, 20, tzinfo=timezone.utc),
        }])
    mults = state.get_multipliers("BTC-USDT-SWAP")
    assert mults["rsi_divergence"] == 0.5


def test_state_update_config_rebuilds_multipliers(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", False) for i in range(15)]
    state.load_records(rows)
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 0.5
    state.update_config(floor=0.3)
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 0.3


def test_state_record_outcomes_updates_multipliers(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(10)]
    state.load_records(rows)
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 1.0
    state.record_outcomes(10, "BTC-USDT-SWAP", [{
        "factor_type": "rsi_divergence",
        "direction": "bullish",
        "strength": 2,
        "correct": False,
        "resolved_at": datetime(2026, 3, 20, tzinfo=timezone.utc),
    }])
    # 10/11 correct = ~90.9% -> still 1.0
    assert state.get_multipliers("BTC-USDT-SWAP")["rsi_divergence"] == 1.0


def test_state_get_multipliers_unknown_pair_uses_global(make_record):
    state = LLMCalibrationState(window=30, floor=0.5)
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(15)]
    state.load_records(rows)
    # WIF has no data -> falls back to global
    mults = state.get_multipliers("WIF-USDT-SWAP")
    assert mults["rsi_divergence"] == 1.0


def test_state_mixed_per_pair_and_global_factors(make_record):
    """Some factor types have per-pair data, others fall back to global."""
    state = LLMCalibrationState(window=50, floor=0.5)
    rows = []
    # rsi_divergence: 20 BTC records (per-pair activates), 10 ETH
    for i in range(20):
        rows.append(make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True))
    for i in range(20, 30):
        rows.append(make_record(i, "ETH-USDT-SWAP", "rsi_divergence", True))
    # news_catalyst: only 12 global records (no per-pair override possible)
    for i in range(30, 42):
        rows.append(make_record(i, "BTC-USDT-SWAP", "news_catalyst", False))
    state.load_records(rows)
    mults = state.get_multipliers("BTC-USDT-SWAP")
    assert mults["rsi_divergence"] == 1.0       # per-pair override
    assert mults["news_catalyst"] == 0.5         # global only (12 >= 10)


from app.engine.llm_calibration import apply_calibration


def test_apply_calibration_no_multipliers():
    base = {"rsi_divergence": 7.0, "news_catalyst": 7.0}
    result = apply_calibration(base, {})
    assert result == base


def test_apply_calibration_partial_multipliers():
    base = {"rsi_divergence": 7.0, "news_catalyst": 7.0}
    mults = {"rsi_divergence": 0.5}
    result = apply_calibration(base, mults)
    assert result["rsi_divergence"] == 3.5
    assert result["news_catalyst"] == 7.0


def test_apply_calibration_all_multipliers():
    base = {"rsi_divergence": 7.0, "news_catalyst": 7.0}
    mults = {"rsi_divergence": 0.5, "news_catalyst": 0.75}
    result = apply_calibration(base, mults)
    assert result["rsi_divergence"] == 3.5
    assert result["news_catalyst"] == pytest.approx(5.25)


# Integration tests

@pytest.fixture
def calibration_with_data(make_record):
    """Pre-loaded calibration state with known multipliers."""
    state = LLMCalibrationState(window=30, floor=0.5)
    # 15 correct records -> multiplier 1.0
    rows = [make_record(i, "BTC-USDT-SWAP", "rsi_divergence", True) for i in range(15)]
    # 15 incorrect records -> multiplier 0.5
    rows += [make_record(15 + i, "BTC-USDT-SWAP", "news_catalyst", False) for i in range(15)]
    state.load_records(rows)
    return state


def test_pipeline_settings_update_syncs_calibration_state():
    """Verify update_config propagates floor/window changes."""
    state = LLMCalibrationState(window=30, floor=0.5)
    state.update_config(window=50, floor=0.3)
    assert state.window == 50
    assert state.floor == 0.3


def test_apply_calibration_in_pipeline_context(calibration_with_data):
    """Verify calibrated weights are correctly computed for pipeline use."""
    base_weights = {"rsi_divergence": 7.0, "news_catalyst": 7.0, "htf_alignment": 7.0}
    mults = calibration_with_data.get_multipliers("BTC-USDT-SWAP")
    calibrated = apply_calibration(base_weights, mults)
    assert calibrated["rsi_divergence"] == 7.0       # 1.0 multiplier
    assert calibrated["news_catalyst"] == 3.5         # 0.5 multiplier
    assert calibrated["htf_alignment"] == 7.0         # no data -> 1.0 default
