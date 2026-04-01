# ML Feature Sync & Graceful Inference Fallback

## Problem

Models are trained locally (GPU) with full historical data including all optional feature groups (order flow, BTC cross-pair, regime). At inference time in production (CPU, Docker), the pipeline reconstructs features from live data — but live collectors may not have flow/BTC data available in Redis/Postgres. When data is missing, `build_feature_matrix()` produces fewer columns than the model's BatchNorm layer expects, causing a dimension mismatch crash.

**Root cause**: Training and inference use separate databases with different data availability. The local training DB may have complete flow data, but the prod DB's flow data depends on live collector uptime and Redis TTLs.

## Solution

Two complementary changes:

1. **Prod → Local data sync** — Train on the same data prod actually has, so the model learns real-world data patterns including gaps
2. **Graceful inference fallback** — When features are missing at inference time, handle it without crashing

---

## 0. Prerequisite: Add Unique Constraint on `order_flow_snapshots`

The `order_flow_snapshots` table currently has only a non-unique index `ix_oflow_pair_ts` on `(pair, timestamp)`. The sync script needs `ON CONFLICT DO NOTHING` upsert semantics, which requires a unique constraint.

### Alembic migration

Add a unique constraint on `(pair, timestamp)` to `order_flow_snapshots`:

```python
# In migration
op.create_unique_constraint("uq_oflow_pair_ts", "order_flow_snapshots", ["pair", "timestamp"])
```

**Before running**: Check for existing duplicates and deduplicate (keep the row with the highest `id` per `(pair, timestamp)` group). The migration should include a pre-step that deletes duplicates:

```sql
DELETE FROM order_flow_snapshots a
USING order_flow_snapshots b
WHERE a.pair = b.pair AND a.timestamp = b.timestamp AND a.id < b.id;
```

### Model change

Update `OrderFlowSnapshot.__table_args__` in `db/models.py`:

```python
__table_args__ = (
    Index("ix_oflow_pair_ts", "pair", "timestamp"),
    UniqueConstraint("pair", "timestamp", name="uq_oflow_pair_ts"),
)
```

---

## 1. Prod → Local Data Sync

### Script: `backend/scripts/sync_prod_data.py`

A CLI script that pulls training-relevant tables from the production Postgres into the local Postgres.

### Tables to sync

| Table | Why | Upsert strategy |
|-------|-----|-----------------|
| `candles` | Core price/volume data for feature matrix | `ON CONFLICT (uq_candle) DO NOTHING` |
| `order_flow_snapshots` | Flow features (funding rate, OI, long/short ratio) | `ON CONFLICT (uq_oflow_pair_ts) DO NOTHING` |

### Interface

The prod database runs inside a Docker container on a remote machine accessible via SSH. The script uses the `sshtunnel` Python library for SSH port-forwarding (handles lifecycle, readiness detection, and cleanup automatically via context manager).

```
python scripts/sync_prod_data.py \
  --ssh user@prod-host \
  --remote-port 5432 \
  --source-db krypton \
  --target postgresql://user:pass@localhost:5432/krypton \
  --days 30 \
  --pairs BTC-USDT-SWAP,ETH-USDT-SWAP
```

**Arguments:**
- `--ssh`: SSH destination for tunnel (e.g., `user@prod-host`). If provided, opens an SSH tunnel via `sshtunnel.SSHTunnelForwarder` to forward the remote Postgres port to a local ephemeral port.
- `--ssh-key`: Path to SSH private key file (default: `~/.ssh/id_rsa`). Avoids passing credentials via CLI args.
- `--remote-port`: Postgres port on the remote machine (default: 5432). This is the host-mapped port of the prod Postgres container.
- `--source-db`: Database name on the remote Postgres (default: `krypton`)
- `--source`: Direct Postgres connection string — alternative to SSH tunnel, for cases where prod DB is directly reachable
- `--target`: Local database connection string (defaults to local dev DB from env/config)
- `--days`: How many days of data to pull (default: 30)
- `--pairs`: Comma-separated pair filter (default: all pairs)

Either `--ssh` or `--source` must be provided.

### Behavior

- Opens SSH tunnel via `sshtunnel.SSHTunnelForwarder` context manager (auto-cleanup on error/exit)
- Queries prod for rows within the date range
- **Flow snapshot dedup**: Before inserting, buckets flow snapshots by `bucket_timestamp()` per pair and keeps only the latest snapshot per bucket. This matches how the training pipeline aggregates flow data and prevents near-duplicate timestamps from producing redundant rows.
- Upserts into local DB using `ON CONFLICT DO NOTHING` (candles use `uq_candle`, flow snapshots use `uq_oflow_pair_ts`)
- Streams in batches (1000 rows), printing progress per batch (`Synced 3000/8640 candles for BTC-USDT-SWAP...`)
- Prints summary: rows synced per table, date range covered, flow data coverage per pair

### Data flow

```
Production Postgres
  ├─ candles table ──────────┐
  └─ order_flow_snapshots ───┤
                             ▼
              sync_prod_data.py (bucket dedup + batch upsert)
                             │
                             ▼
                    Local Postgres
                             │
                             ▼
                  Local training (GPU)
                             │
                             ▼
              Model checkpoint + config
                             │
                             ▼
              Deploy to prod container
```

---

## 2. Graceful Inference Fallback

### What already exists

The predictor infrastructure for handling mismatched features is **already implemented**:

- `Predictor.set_available_features(names)` (`predictor.py:88–117`) builds index mappings from available columns to the model's expected layout, logging warnings for missing features
- `Predictor._map_features(features)` (`predictor.py:119–129`) uses numpy vectorized gather to remap columns, zero-filling missing positions
- `EnsemblePredictor` has identical methods (`ensemble_predictor.py:127–163`)
- `predict()` always returns a dict (either a real prediction or `_NEUTRAL_RESULT` with direction=NEUTRAL, confidence=0.0) — it never returns `None`
- `run_pipeline` wraps all ML inference in try/except; on any exception, sets `ml_available = False` and continues with indicator-only scoring
- `blend_with_ml()` returns `indicator_preliminary` unchanged when `ml_score` or `ml_confidence` is `None`, or when confidence < threshold (0.65)

### What's missing (the actual bug)

Currently, `set_available_features()` is only called at **model reload time** with the feature names from the training config. If the config says `flow_used=True` but flow data isn't available at inference time, the predictor still expects flow columns. `build_feature_matrix()` produces fewer columns → `_map_features()` can't find them → zero-fills, but this is never triggered because the pipeline only builds features that match the config flags, not the runtime reality.

The fix is **~10 lines in `main.py:run_pipeline`**: call `set_available_features()` with actual runtime availability before each prediction.

### Change to `main.py` (run_pipeline inference section)

After building the feature matrix, recompute actual feature availability and update the predictor:

```python
# Determine what was actually available at runtime
actual_flow = flow_for_features is not None
actual_regime = ml_regime is not None
actual_btc = ml_btc_df is not None

actual_names = get_feature_names(
    flow_used=actual_flow,
    regime_used=actual_regime,
    btc_used=actual_btc,
)
ml_predictor.set_available_features(actual_names)
```

### Short-circuit optimization

Add to both `set_available_features()` implementations: skip recomputing the mapping if the names list hasn't changed since last call.

```python
def set_available_features(self, names: list[str]):
    if names == self._available_features:
        return  # mapping unchanged
    # ... existing logic ...
```

### Confidence penalty for missing features

When features are missing, the prediction is less reliable. Apply a proportional discount **before** the existing uncertainty/drift reductions, since it represents a data quality issue upstream of model uncertainty:

```python
# Applied first in predict(), before MC variance / drift / staleness penalties
missing_ratio = len(missing_features) / len(expected_features)
confidence_penalty = 1.0 - (missing_ratio * 0.5)  # 0% missing → 1.0, 100% missing → 0.5
raw_confidence = raw_confidence * confidence_penalty
```

**Full confidence reduction chain** (in order):
1. **Missing feature penalty** (new) — data quality discount, proportional to missing column ratio
2. **MC dropout variance** / **Ensemble disagreement** — epistemic uncertainty from model
3. **Feature drift penalty** — distribution shift detection
4. **Staleness cap** — time-based max confidence (Predictor: 0.3 after 14d; EnsemblePredictor: partial cap at 2 members)

The 0.5 floor prevents ML from being completely zeroed out — even degraded predictions may have value. The signal engine's existing ML confidence threshold (0.65 in `blend_with_ml`) will naturally filter out low-confidence predictions.

### Where to store missing feature count

Both `Predictor` and `EnsemblePredictor` already compute `missing` in `set_available_features()`. Store it as `self._n_missing_features = len(missing)` and `self._n_expected_features = len(expected)` so `predict()` can apply the penalty without recomputation.

### Error handling hierarchy (existing behavior, unchanged)

1. **All features available**: Predict normally, full confidence
2. **Some features missing**: Zero-fill via `_map_features()`, predict with confidence penalty, log warning
3. **Prediction raises exception**: Caught by `run_pipeline` try/except, `ml_available = False`, pipeline continues without ML
4. **No model loaded**: Skip ML entirely (existing behavior)

---

## What This Does NOT Change

- **Training code**: No changes to `trainer.py` or `ml.py` training orchestration. The training pipeline already correctly determines `flow_used`/`regime_used`/`btc_used` based on data coverage.
- **Feature matrix construction**: `build_feature_matrix()` continues to conditionally include features based on data availability. No zero-filling at the feature level.
- **Model config format**: `ensemble_config.json` / `model_config.json` schema stays the same.
- **Predictor reload**: `_reload_predictors()` still loads config flags and calls `set_available_features()` at load time. The new runtime call in `run_pipeline` overrides this per-cycle.
- **Predictor return contract**: `predict()` continues to return a dict (never `None`). `_NEUTRAL_RESULT` is returned for insufficient data.

## Testing

### New file: `tests/ml/test_feature_fallback.py`

- **test_predictor_fewer_features**: Load a predictor with config expecting 36 features, call `set_available_features()` with 24 names, verify `_map_features()` produces correct shape (n, 36) with zeros in missing positions. No crash.
- **test_predictor_matching_features**: Call `set_available_features()` with exact expected names, verify no-op mapping, full confidence (no missing-feature penalty).
- **test_set_available_features_short_circuit**: Call `set_available_features()` twice with the same names, verify mapping is only computed once.
- **test_confidence_penalty_scaling**: Verify penalty scales correctly: 0 missing → 1.0, 3/36 missing → ~0.958, 12/36 missing → ~0.833, 36/36 missing → 0.5.
- **test_confidence_penalty_order**: Verify missing-feature penalty is applied before MC variance and drift penalties (mock the reduction chain, check intermediate values).

### New file: `tests/ml/test_pipeline_ml_fallback.py`

- **test_run_pipeline_continues_on_ml_exception**: Patch predictor to raise during `predict()`, verify pipeline completes with `ml_available = False` and produces a signal without ML blending.

### Sync script: manual testing

- Test against the existing Docker Compose Postgres (use two different databases in the same instance as source/target)
- Verify: duplicate runs don't create duplicate rows (upsert idempotency)
- Verify: flow snapshot bucketing deduplicates correctly
- Verify: `--ssh` tunnel connects and auto-cleans on Ctrl+C

### New dependency

- `sshtunnel` — add to sync script's imports (dev dependency only, not required for production container)
