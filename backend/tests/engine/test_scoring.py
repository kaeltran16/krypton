# backend/tests/engine/test_scoring.py
from math import isclose
from app.engine.scoring import sigmoid_score, sigmoid_scale


class TestSigmoidScore:
    def test_center_returns_zero(self):
        assert sigmoid_score(0, center=0, steepness=1) == 0
        assert sigmoid_score(50, center=50, steepness=0.1) == 0

    def test_positive_input_returns_positive(self):
        result = sigmoid_score(10, center=0, steepness=0.1, max_score=25)
        assert result > 0

    def test_negative_input_returns_negative(self):
        result = sigmoid_score(-10, center=0, steepness=0.1, max_score=25)
        assert result < 0

    def test_bounded_by_max_score(self):
        assert sigmoid_score(1000, center=0, steepness=1, max_score=25) < 25.01
        assert sigmoid_score(-1000, center=0, steepness=1, max_score=25) > -25.01

    def test_monotonic(self):
        scores = [sigmoid_score(v, center=0, steepness=0.1) for v in range(-50, 51)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]

    def test_symmetric(self):
        pos = sigmoid_score(10, center=0, steepness=0.5, max_score=30)
        neg = sigmoid_score(-10, center=0, steepness=0.5, max_score=30)
        assert isclose(pos, -neg, rel_tol=1e-9)


class TestSigmoidScale:
    def test_center_returns_half(self):
        assert isclose(sigmoid_scale(20, center=20, steepness=0.15), 0.5)

    def test_high_value_approaches_one(self):
        assert sigmoid_scale(50, center=20, steepness=0.15) > 0.95

    def test_low_value_approaches_zero(self):
        assert sigmoid_scale(0, center=20, steepness=0.15) < 0.1

    def test_always_between_zero_and_one(self):
        for v in range(-100, 200):
            result = sigmoid_scale(v, center=20, steepness=0.15)
            assert 0 <= result <= 1

    def test_monotonic(self):
        scores = [sigmoid_scale(v, center=20, steepness=0.15) for v in range(0, 60)]
        for i in range(1, len(scores)):
            assert scores[i] >= scores[i - 1]
