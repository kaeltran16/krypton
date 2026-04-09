# ML Feature Sync & Graceful Inference Fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure ML inference never crashes due to missing feature groups, and provide a script to sync prod data locally for training.

**Architecture:** Two independent changes: (1) a standalone CLI sync script using psycopg2 + SSH tunneling, (2) changes to predictor and inference code so missing features are zero-filled with a confidence penalty instead of crashing.

**Tech Stack:** Python 3.11, psycopg2, argparse, subprocess (SSH tunnel), PyTorch, numpy, pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `backend/scripts/sync_prod_data.py` | CLI script to sync candles + order_flow_snapshots from prod to local |
| Modify | `backend/app/ml/predictor.py:88-117` | Add short-circuit to `set_available_features`, add `missing_feature_ratio` property, wrap `predict` with try/except returning `None` |
| Modify | `backend/app/ml/ensemble_predictor.py:127-152` | Same changes as predictor.py |
| Modify | `backend/app/main.py:1112-1119` | Call `set_available_features` with actual runtime feature names before prediction, apply confidence penalty |
| Modify | `backend/tests/ml/test_predictor.py` | Add tests for missing features fallback + confidence penalty |
| Modify | `backend/tests/ml/test_ensemble_predictor.py` | Add tests for missing features fallback + confidence penalty |

---

### Task 1: Predictor graceful fallback — tests

**Files:**
- Modify: `backend/tests/ml/test_predictor.py`

- [ ] **Step 1: Write failing tests for missing feature handling**

Add a new test class at the end of `test_predictor.py`:

```python
class TestGracefulFallback:

    def test_predict_with_fewer_features_no_crash(self):
        """Predictor should zero-fill missing features instead of crashing."""
        # Model trained with 24 features
        feature_names = [f"feat_{i}" for i in range(24)]
        path = _save_model(input_size=24, extra_config={"feature_names": feature_names})
        predictor = Predictor(path)
        # Runtime only has 20 features (missing 4)
        runtime_names = [f"feat_{i}" for i in range(20)]
        predictor.set_available_features(runtime_names)
        features = np.random.randn(50, 20).astype(np.float32)
        result = predictor.predict(features)
        assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")

    def test_missing_feature_ratio_reported(self):
        """Predictor should expose ratio of missing features."""
        feature_names = [f"feat_{i}" for i in range(24)]
        path = _save_model(input_size=24, extra_config={"feature_names": feature_names})
        predictor = Predictor(path)
        runtime_names = [f"feat_{i}" for i in range(18)]  # 6 missing out of 24
        predictor.set_available_features(runtime_names)
        assert predictor.missing_feature_ratio == pytest.approx(6 / 24)

    def test_no_missing_features_ratio_zero(self):
        """When all features present, missing ratio is 0."""
        feature_names = [f"feat_{i}" for i in range(24)]
        path = _save_model(input_size=24, extra_config={"feature_names": feature_names})
        predictor = Predictor(path)
        predictor.set_available_features(feature_names)
        assert predictor.missing_feature_ratio == 0.0

    def test_set_available_features_short_circuits(self):
        """Calling set_available_features with same names should not recompute."""
        feature_names = [f"feat_{i}" for i in range(15)]
        path = _save_model(input_size=15, extra_config={"feature_names": feature_names})
        predictor = Predictor(path)
        predictor.set_available_features(feature_names)
        first_map = predictor._feature_map
        predictor.set_available_features(feature_names)
        assert predictor._feature_map is first_map  # same object, not recomputed

    def test_predict_exception_returns_none(self):
        """If predict() raises internally, it should return None."""
        feature_names = [f"feat_{i}" for i in range(15)]
        path = _save_model(input_size=15, extra_config={"feature_names": feature_names})
        predictor = Predictor(path)
        predictor.set_available_features(feature_names)
        # Feed a matrix with wrong dtype to trigger an error inside torch
        features = np.array([["bad"] * 15] * 50)  # string array
        result = predictor.predict(features)
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py::TestGracefulFallback -v`

Expected: FAIL — `missing_feature_ratio` attribute doesn't exist, `predict` doesn't return `None` on error.

---

### Task 2: Predictor graceful fallback — implementation

**Files:**
- Modify: `backend/app/ml/predictor.py:88-198`

- [ ] **Step 1: Add short-circuit and missing_feature_ratio to set_available_features**

In `predictor.py`, replace `set_available_features` and add the property. Change lines 88-117:

```python
    @property
    def missing_feature_ratio(self) -> float:
        """Fraction of expected features not available at inference time."""
        if self._feature_map is None or not self._expected_features:
            return 0.0
        missing = sum(1 for idx in self._feature_map if idx == -1)
        return missing / len(self._expected_features)

    def set_available_features(self, names: list[str]):
        """Set the feature names available at inference time.

        Builds a mapping from available feature columns to the model's expected layout.
        Short-circuits if names haven't changed since last call.
        """
        if self._available_features == names:
            return

        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            return

        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)

        if missing:
            logger.warning("Missing features for model (filled with 0): %s", missing)

        # Precompute numpy index arrays for vectorized gather in _map_features
        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map
```

- [ ] **Step 2: Wrap predict() with try/except to return None on failure**

In `predictor.py`, wrap the body of `predict()` (lines 131-198). Change the method to:

```python
    def predict(self, features: np.ndarray) -> dict | None:
        """Run inference on a feature matrix.

        Args:
            features: (n_candles, n_features) array. Uses last seq_len rows.

        Returns:
            dict with direction, confidence, sl_atr, tp1_atr, tp2_atr, mc_variance.
            Returns None if inference fails for any reason.
        """
        try:
            return self._predict_inner(features)
        except Exception as e:
            logger.error("Predictor inference failed: %s", e, exc_info=True)
            return None

    def _predict_inner(self, features: np.ndarray) -> dict:
        if len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        # Feature mapping by name (if available)
        features = self._map_features(features)

        # Take last seq_len candles
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        temperature = self._temperature

        # Only enable Dropout layers, NOT BatchNorm
        self.model.eval()
        for m in self.model.modules():
            if isinstance(m, nn.Dropout):
                m.train()

        all_probs = []
        all_regs = []
        for _ in range(MC_DROPOUT_PASSES):
            with torch.no_grad():
                dir_logits, reg_out = self.model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        self.model.eval()  # restore all layers to eval

        mean_probs = np.mean(all_probs, axis=0)
        mean_reg = np.mean(all_regs, axis=0)

        # Epistemic uncertainty: variance across passes
        prob_variance = float(np.mean(np.var(all_probs, axis=0)))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        # Reduce confidence proportionally to uncertainty
        uncertainty_penalty = min(1.0, prob_variance * 10)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for stale models
        confidence = min(confidence, self._max_confidence)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "mc_variance": prob_variance,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_predictor.py -v`

Expected: All tests PASS including the new `TestGracefulFallback` tests and all existing tests.

- [ ] **Step 4: Commit**

```bash
git add backend/app/ml/predictor.py backend/tests/ml/test_predictor.py
git commit -m "feat(ml): add graceful fallback to Predictor for missing features"
```

---

### Task 3: EnsemblePredictor graceful fallback — tests

**Files:**
- Modify: `backend/tests/ml/test_ensemble_predictor.py`

- [ ] **Step 1: Write failing tests for ensemble missing feature handling**

Add at the end of `test_ensemble_predictor.py`:

```python
def test_predict_with_fewer_features_no_crash(ensemble_checkpoint):
    """EnsemblePredictor should zero-fill missing features instead of crashing."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    # Config has feature_names f0..f14 (15 features)
    # Runtime only has 10
    runtime_names = [f"f{i}" for i in range(10)]
    pred.set_available_features(runtime_names)
    features = np.random.randn(20, 10).astype(np.float32)
    result = pred.predict(features)
    assert result["direction"] in ("LONG", "SHORT", "NEUTRAL")


def test_missing_feature_ratio(ensemble_checkpoint):
    """EnsemblePredictor should expose ratio of missing features."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    runtime_names = [f"f{i}" for i in range(10)]  # 5 missing out of 15
    pred.set_available_features(runtime_names)
    assert pred.missing_feature_ratio == pytest.approx(5 / 15)


def test_no_missing_features_ratio_zero(ensemble_checkpoint):
    """When all features present, missing ratio is 0."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    all_names = [f"f{i}" for i in range(15)]
    pred.set_available_features(all_names)
    assert pred.missing_feature_ratio == 0.0


def test_set_available_features_short_circuits(ensemble_checkpoint):
    """Calling set_available_features with same names should not recompute."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    names = [f"f{i}" for i in range(15)]
    pred.set_available_features(names)
    first_map = pred._feature_map
    pred.set_available_features(names)
    assert pred._feature_map is first_map


def test_predict_exception_returns_none(ensemble_checkpoint):
    """If predict() raises internally, it should return None."""
    pred = EnsemblePredictor(ensemble_checkpoint)
    names = [f"f{i}" for i in range(15)]
    pred.set_available_features(names)
    features = np.array([["bad"] * 15] * 20)  # string array
    result = pred.predict(features)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py::test_predict_with_fewer_features_no_crash tests/ml/test_ensemble_predictor.py::test_missing_feature_ratio tests/ml/test_ensemble_predictor.py::test_predict_exception_returns_none -v`

Expected: FAIL — `missing_feature_ratio` doesn't exist, `predict` doesn't return `None` on error.

---

### Task 4: EnsemblePredictor graceful fallback — implementation

**Files:**
- Modify: `backend/app/ml/ensemble_predictor.py:127-222`

- [ ] **Step 1: Add short-circuit, missing_feature_ratio, and try/except to EnsemblePredictor**

In `ensemble_predictor.py`, add the `missing_feature_ratio` property before `set_available_features` (around line 126):

```python
    @property
    def missing_feature_ratio(self) -> float:
        """Fraction of expected features not available at inference time."""
        if self._feature_map is None or not self._expected_features:
            return 0.0
        missing = sum(1 for idx in self._feature_map if idx == -1)
        return missing / len(self._expected_features)
```

Replace `set_available_features` (lines 127-152) to add the short-circuit:

```python
    def set_available_features(self, names: list[str]):
        """Set feature names available at inference time."""
        if self._available_features == names:
            return

        self._available_features = names
        expected = self._expected_features
        if not expected:
            self._feature_map = None
            return

        available_idx = {name: i for i, name in enumerate(names)}
        raw_map = []
        missing = []
        for name in expected:
            idx = available_idx.get(name, -1)
            raw_map.append(idx)
            if idx == -1:
                missing.append(name)

        if missing:
            logger.warning("Missing features for ensemble (filled with 0): %s", missing)

        out_idx = np.array([i for i, c in enumerate(raw_map) if c >= 0], dtype=np.intp)
        in_idx = np.array([c for c in raw_map if c >= 0], dtype=np.intp)
        valid = out_idx < self.input_size
        self._out_idx = out_idx[valid]
        self._in_idx = in_idx[valid]
        self._feature_map = raw_map
```

Replace `predict` (lines 165-222) with try/except wrapper:

```python
    def predict(self, features: np.ndarray) -> dict | None:
        """Run ensemble inference.

        Returns dict matching Predictor.predict() interface plus ensemble_disagreement.
        Returns None if inference fails for any reason.
        """
        try:
            return self._predict_inner(features)
        except Exception as e:
            logger.error("Ensemble inference failed: %s", e, exc_info=True)
            return None

    def _predict_inner(self, features: np.ndarray) -> dict:
        if self.n_members == 0 or len(features) < self.seq_len:
            return dict(_NEUTRAL_RESULT)

        features = self._map_features(features)
        window = features[-self.seq_len:]
        x = torch.tensor(window, dtype=torch.float32).unsqueeze(0).to(self.device)

        all_probs = []
        all_regs = []
        for model, temperature in zip(self._models, self._temperatures):
            with torch.no_grad():
                dir_logits, reg_out = model(x)
                probs = torch.softmax(dir_logits / temperature, dim=1).squeeze(0).cpu().numpy()
                all_probs.append(probs)
                all_regs.append(reg_out.squeeze(0).cpu().numpy())

        all_probs = np.array(all_probs)
        all_regs = np.array(all_regs)
        weights = np.array(self._weights)
        weights = weights / weights.sum()

        # Weighted mean
        mean_probs = np.average(all_probs, axis=0, weights=weights)
        mean_reg = np.average(all_regs, axis=0, weights=weights)

        # Weighted disagreement
        diff = all_probs - mean_probs[None, :]
        disagreement = float(np.average((diff ** 2).mean(axis=1), weights=weights))

        direction_idx = int(np.argmax(mean_probs))
        raw_confidence = float(mean_probs[direction_idx])

        uncertainty_penalty = min(1.0, disagreement * self._disagreement_scale)
        confidence = raw_confidence * (1.0 - uncertainty_penalty)

        drift_pen = feature_drift_penalty(
            window, self._drift_stats, top_k=3, config=self._drift_config,
        )
        confidence *= (1.0 - drift_pen)

        # Cap confidence for partial ensembles
        if self.n_members == 2:
            confidence = min(confidence, self._confidence_cap_partial)

        return {
            "direction": DIRECTION_MAP[direction_idx],
            "confidence": confidence,
            "sl_atr": float(mean_reg[0]),
            "tp1_atr": float(mean_reg[1]),
            "tp2_atr": float(mean_reg[2]),
            "ensemble_disagreement": disagreement,
            "drift_penalty": drift_pen,
        }
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/test_ensemble_predictor.py -v`

Expected: All tests PASS including new fallback tests and all existing tests.

- [ ] **Step 3: Commit**

```bash
git add backend/app/ml/ensemble_predictor.py backend/tests/ml/test_ensemble_predictor.py
git commit -m "feat(ml): add graceful fallback to EnsemblePredictor for missing features"
```

---

### Task 5: Runtime feature name detection in inference pipeline

**Files:**
- Modify: `backend/app/main.py:1112-1135`

- [ ] **Step 1: Update run_pipeline to pass actual runtime feature names to predictor**

In `main.py`, replace lines 1112-1135 (the feature matrix build + prediction + score conversion):

```python
            feature_matrix = build_feature_matrix(
                df,
                order_flow=flow_for_features,
                regime=ml_regime,
                trend_conviction=ml_conviction,
                btc_candles=ml_btc_df,
            )

            # Tell predictor which features are actually available this cycle
            from app.ml.features import get_feature_names
            actual_names = get_feature_names(
                flow_used=flow_for_features is not None,
                regime_used=ml_regime is not None,
                btc_used=ml_btc_df is not None,
            )
            ml_predictor.set_available_features(actual_names)

            ml_prediction = ml_predictor.predict(feature_matrix)

            if ml_prediction is None:
                logger.warning(
                    "ML prediction returned None for %s:%s, skipping ML scoring",
                    pair, timeframe,
                )
            else:
                ml_direction = ml_prediction["direction"]
                ml_confidence = ml_prediction["confidence"]

                # Apply confidence penalty for missing features
                missing_ratio = ml_predictor.missing_feature_ratio
                if missing_ratio > 0:
                    confidence_penalty = 1.0 - (missing_ratio * 0.5)
                    ml_confidence *= confidence_penalty
                    logger.info(
                        "ML confidence penalized for %s:%s — %.0f%% features missing, "
                        "penalty=%.2f, adjusted_confidence=%.3f",
                        pair, timeframe, missing_ratio * 100,
                        confidence_penalty, ml_confidence,
                    )

                # Convert ML output to -100..+100 score
                # Center at 1/3 (uniform probability for 3-class softmax)
                # so confidence=0.33 → 0, confidence=1.0 → 100
                if ml_direction == "NEUTRAL":
                    ml_score = 0.0
                else:
                    centered = (ml_confidence - 1 / 3) / (2 / 3) * 100
                    ml_score = centered if ml_direction == "LONG" else -centered

                ml_available = True
```

Note: the `from app.ml.features import get_feature_names` import is already at the top of the `if ml_predictor is not None` block (line 1014). Move it up there if not already present, or reuse the existing import.

- [ ] **Step 2: Run the full ML test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/ -v`

Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat(ml): detect runtime feature availability and penalize confidence for missing features"
```

---

### Task 6: Prod-to-local data sync script

**Files:**
- Create: `backend/scripts/sync_prod_data.py`

- [ ] **Step 1: Create the sync script**

Create `backend/scripts/sync_prod_data.py`:

```python
"""Sync candles and order_flow_snapshots from production Postgres to local.

Usage:
    # Via SSH tunnel (prod DB in Docker on remote host):
    python scripts/sync_prod_data.py \
        --ssh user@prod-host \
        --remote-port 5432 \
        --source-db krypton \
        --target postgresql://user:pass@localhost:5432/krypton \
        --days 30

    # Via direct connection string:
    python scripts/sync_prod_data.py \
        --source postgresql://user:pass@prod-host:5432/krypton \
        --target postgresql://user:pass@localhost:5432/krypton \
        --days 30
"""

import argparse
import json
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import psycopg2
import psycopg2.extras


BATCH_SIZE = 1000

TABLES = {
    "candles": {
        "columns": [
            "pair", "timeframe", "timestamp",
            "open", "high", "low", "close", "volume",
        ],
        "conflict": "ON CONFLICT ON CONSTRAINT uq_candle DO NOTHING",
        "filter_col": "timestamp",
        "pair_col": "pair",
    },
    "order_flow_snapshots": {
        "columns": [
            "pair", "timestamp",
            "funding_rate", "open_interest", "oi_change_pct",
            "long_short_ratio", "cvd_delta",
        ],
        "conflict": "ON CONFLICT DO NOTHING",
        "filter_col": "timestamp",
        "pair_col": "pair",
    },
}


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@contextmanager
def ssh_tunnel(ssh_dest: str, remote_port: int):
    """Open an SSH tunnel and yield the local port."""
    local_port = _find_free_port()
    cmd = [
        "ssh", "-N", "-L",
        f"{local_port}:localhost:{remote_port}",
        ssh_dest,
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    # Wait for tunnel to be ready
    for _ in range(30):
        try:
            with socket.create_connection(("localhost", local_port), timeout=1):
                break
        except OSError:
            time.sleep(0.5)
    else:
        proc.terminate()
        raise RuntimeError(f"SSH tunnel to {ssh_dest}:{remote_port} failed to open")
    try:
        yield local_port
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def sync_table(
    source_conn,
    target_conn,
    table_name: str,
    since: datetime,
    pairs: list[str] | None,
) -> int:
    """Copy rows from source to target for one table. Returns row count."""
    spec = TABLES[table_name]
    cols = spec["columns"]
    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    # Build WHERE clause
    where = f"WHERE {spec['filter_col']} >= %s"
    params: list = [since]
    if pairs:
        where += f" AND {spec['pair_col']} = ANY(%s)"
        params.append(pairs)

    query = f"SELECT {col_list} FROM {table_name} {where} ORDER BY {spec['filter_col']}"

    insert_sql = (
        f"INSERT INTO {table_name} ({col_list}) VALUES ({placeholders}) "
        f"{spec['conflict']}"
    )

    total = 0
    with source_conn.cursor("sync_cursor") as src_cur:
        src_cur.itersize = BATCH_SIZE
        src_cur.execute(query, params)

        with target_conn.cursor() as tgt_cur:
            batch = []
            for row in src_cur:
                batch.append(row)
                if len(batch) >= BATCH_SIZE:
                    psycopg2.extras.execute_batch(tgt_cur, insert_sql, batch)
                    total += len(batch)
                    batch = []
            if batch:
                psycopg2.extras.execute_batch(tgt_cur, insert_sql, batch)
                total += len(batch)

        target_conn.commit()

    return total


def compute_flow_coverage(target_conn, since: datetime, pairs: list[str] | None) -> dict:
    """Compute order flow coverage per pair in the target DB."""
    query = """
        SELECT ofs.pair,
               COUNT(DISTINCT date_trunc('hour', ofs.timestamp)) AS flow_hours,
               COUNT(DISTINCT date_trunc('hour', c.timestamp)) AS candle_hours
        FROM candles c
        LEFT JOIN order_flow_snapshots ofs
            ON c.pair = ofs.pair
            AND date_trunc('hour', c.timestamp) = date_trunc('hour', ofs.timestamp)
        WHERE c.timestamp >= %s
    """
    params: list = [since]
    if pairs:
        query += " AND c.pair = ANY(%s)"
        params.append(pairs)
    query += " GROUP BY ofs.pair"

    with target_conn.cursor() as cur:
        cur.execute(query, params)
        results = {}
        for row in cur.fetchall():
            pair, flow_h, candle_h = row
            if pair and candle_h > 0:
                results[pair] = flow_h / candle_h
        return results


def main():
    parser = argparse.ArgumentParser(description="Sync prod data to local for ML training")
    parser.add_argument("--ssh", help="SSH destination (e.g. user@host)")
    parser.add_argument("--remote-port", type=int, default=5432, help="Remote Postgres port")
    parser.add_argument("--source-db", default="krypton", help="Remote database name")
    parser.add_argument("--source-user", default="postgres", help="Remote database user")
    parser.add_argument("--source", help="Direct source connection string (alternative to --ssh)")
    parser.add_argument("--target", required=True, help="Target connection string")
    parser.add_argument("--days", type=int, default=30, help="Days of data to sync")
    parser.add_argument("--pairs", help="Comma-separated pair filter")
    args = parser.parse_args()

    if not args.ssh and not args.source:
        parser.error("Either --ssh or --source is required")

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    pairs = [p.strip() for p in args.pairs.split(",")] if args.pairs else None

    print(f"Syncing data since {since.isoformat()} ({args.days} days)")
    if pairs:
        print(f"Pairs: {', '.join(pairs)}")

    target_conn = psycopg2.connect(args.target)

    try:
        if args.ssh:
            with ssh_tunnel(args.ssh, args.remote_port) as local_port:
                source_dsn = (
                    f"host=localhost port={local_port} "
                    f"dbname={args.source_db} user={args.source_user}"
                )
                source_conn = psycopg2.connect(source_dsn)
                try:
                    for table in TABLES:
                        count = sync_table(source_conn, target_conn, table, since, pairs)
                        print(f"  {table}: {count} rows synced")
                finally:
                    source_conn.close()
        else:
            source_conn = psycopg2.connect(args.source)
            try:
                for table in TABLES:
                    count = sync_table(source_conn, target_conn, table, since, pairs)
                    print(f"  {table}: {count} rows synced")
            finally:
                source_conn.close()

        # Coverage report
        coverage = compute_flow_coverage(target_conn, since, pairs)
        if coverage:
            print("\nFlow data coverage:")
            for pair, cov in sorted(coverage.items()):
                print(f"  {pair}: {cov:.1%}")
        else:
            print("\nNo flow data coverage found.")

    finally:
        target_conn.close()

    print("\nDone.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script parses arguments correctly**

Run: `python backend/scripts/sync_prod_data.py --help`

Expected: Help text prints with all arguments listed. (This runs locally, not in Docker, since psycopg2 is a local dependency for training.)

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/sync_prod_data.py
git commit -m "feat(ml): add prod-to-local data sync script with SSH tunnel support"
```

---

### Task 7: Final verification

**Files:**
- None (verification only)

- [ ] **Step 1: Run the full ML test suite**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/ml/ -v`

Expected: All tests PASS (existing + new fallback tests).

- [ ] **Step 2: Run all backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`

Expected: All tests PASS.

- [ ] **Step 3: Verify no regressions in main.py by checking the import is reachable**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -c "from app.ml.features import get_feature_names; print(get_feature_names(flow_used=True, regime_used=True, btc_used=True)); print('OK')"`

Expected: Prints the full feature name list (36 entries) and "OK".
