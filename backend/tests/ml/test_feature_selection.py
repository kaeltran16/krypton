import numpy as np
from app.ml.features import select_features_by_importance


class TestFeatureSelection:

    def test_drops_low_importance_features(self):
        importances = np.array([0.30, 0.25, 0.20, 0.15, 0.05, 0.03, 0.02])
        names = ["f0", "f1", "f2", "f3", "f4", "f5", "f6"]
        selected, indices = select_features_by_importance(
            importances, names, threshold=0.01,
        )
        # f5 (3%) and f6 (2%) should be kept (above 1% of total)
        # All features are above 1% threshold in this case
        assert len(selected) == 7

    def test_drops_below_threshold(self):
        importances = np.array([0.50, 0.30, 0.15, 0.04, 0.005, 0.005])
        names = ["f0", "f1", "f2", "f3", "f4", "f5"]
        selected, indices = select_features_by_importance(
            importances, names, threshold=0.01,
        )
        # f4 and f5 are each 0.5% of total — below 1%
        assert "f4" not in selected
        assert "f5" not in selected
        assert len(selected) == 4
