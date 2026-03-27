# Multi-Timeframe Confluence Redesign — Cleanup Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the remaining gaps identified in the spec review — stale references, mismatched defaults, and a broken test assertion — so the confluence redesign is fully consistent between code, DB model defaults, and tests.

**Architecture:** Four independent fixes to different subsystems: backend API route, optimizer, DB model defaults, and frontend signal display. No changes to core confluence scoring logic — that's already complete and working.

**Tech Stack:** Python/FastAPI (backend), SQLAlchemy (models), Alembic (migrations), React/TypeScript (frontend)

**Spec:** `docs/superpowers/specs/2026-03-27-multi-timeframe-confluence-redesign.md`

---

### Task 1: Fix routes.py — convert positional args to keyword args

**Files:**
- Modify: `backend/app/api/routes.py:556`

- [ ] **Step 1: Fix the compute_preliminary_score call**

Change line 556 from positional args to keyword args so the call is explicit and won't silently break if the combiner signature changes:

```python
        prelim = compute_preliminary_score(
            technical_score=tech["score"],
            order_flow_score=flow["score"],
            tech_weight=0.50,
            flow_weight=0.25,
        )["score"]
```

- [ ] **Step 2: Run combiner and pipeline tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_combiner.py tests/test_pipeline.py -v`
Expected: All PASS (this is a no-op refactor — behavior unchanged)

---

### Task 2: Fix optimizer.py — remove dangling confluence_dampening reference

**Files:**
- Modify: `backend/app/engine/optimizer.py:415`

- [ ] **Step 1: Remove "confluence_dampening" from the mr_pressure key tuple**

The `mr_pressure` param group only defines `max_cap_shift`, `obv_weight`, and `mr_llm_trigger` (see `param_groups.py:430-444`). The `"confluence_dampening"` key in the optimizer tuple references a param that no longer exists. Remove it:

Change line 415 from:
```python
                                    for k in ("max_cap_shift", "confluence_dampening", "mr_llm_trigger")
```

To:
```python
                                    for k in ("max_cap_shift", "mr_llm_trigger")
```

- [ ] **Step 2: Run mr_pressure tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_mr_pressure.py -v`
Expected: All PASS

---

### Task 3: Update RegimeWeights model defaults to match DEFAULT_OUTER_WEIGHTS

The `RegimeWeights` model in `db/models.py` still has the old 5-source outer weight defaults (e.g., `trending_tech_weight=0.45`) from before the 6-source rebalance. These should match the values in `regime.py:DEFAULT_OUTER_WEIGHTS`. The `_build_regime_weights` function in the optimizer reads `DEFAULT_OUTER_WEIGHTS` at runtime (not model defaults), so the discrepancy only affects new DB rows created via ORM — but consistency matters. Existing DB rows with stale 5-source defaults will self-correct as the optimizer re-tunes them; no data migration needed.

**Files:**
- Modify: `backend/app/db/models.py:386-410`
- Modify: `backend/tests/engine/test_de_sweep.py:202`
- Create: `backend/app/db/migrations/versions/b5c6d7e8f9a0_rebalance_regime_outer_weight_defaults.py`

- [ ] **Step 1: Update the model outer weight defaults**

In `backend/app/db/models.py`, update lines 386-410 to match `DEFAULT_OUTER_WEIGHTS` from `regime.py`. The confluence weights (lines 413-416) are already correct and don't change.

```python
    # Outer weights (4 regimes x 4 weights = 16 floats)
    trending_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.36)
    trending_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.20)
    trending_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.14)
    trending_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.09)

    ranging_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.32)
    ranging_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.14)
    ranging_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.22)
    ranging_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.14)

    volatile_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.34)
    volatile_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.18)
    volatile_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.16)
    volatile_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.10)

    steady_tech_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.36, server_default="0.36")
    steady_flow_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.16, server_default="0.16")
    steady_onchain_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.16, server_default="0.16")
    steady_pattern_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.10, server_default="0.10")

    # Liquidation weights (4 regimes x 1 weight)
    trending_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.07, server_default="0.07")
    ranging_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.10, server_default="0.10")
    volatile_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.10, server_default="0.10")
    steady_liquidation_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.08, server_default="0.08")
```

- [ ] **Step 2: Fix stale test assertion in test_de_sweep.py**

In `backend/tests/engine/test_de_sweep.py`, line 202 asserts `trending_tech_weight == 0.42` but `DEFAULT_OUTER_WEIGHTS["trending"]["tech"]` is `0.36`. Fix the assertion:

```python
        assert rw.trending_tech_weight == 0.36       # from DEFAULT_OUTER_WEIGHTS
        assert rw.ranging_tech_weight == 0.32        # from DEFAULT_OUTER_WEIGHTS
        assert rw.volatile_flow_weight == 0.18       # from DEFAULT_OUTER_WEIGHTS
        assert rw.volatile_pattern_weight == 0.10    # from DEFAULT_OUTER_WEIGHTS
```

This replaces the existing two assertions (lines 202-203). The extra assertions cover values that actually changed between the old and new defaults, giving stronger confidence the full rebalance is wired correctly.

- [ ] **Step 3: Create Alembic migration for server_default updates**

Create `backend/app/db/migrations/versions/b5c6d7e8f9a0_rebalance_regime_outer_weight_defaults.py`:

```python
"""rebalance regime outer weight defaults for 6-source confluence

Revision ID: b5c6d7e8f9a0
Revises: c4f5a6b7d8e9
Create Date: 2026-03-28
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, Sequence[str], None] = 'c4f5a6b7d8e9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Update server_default values for outer weights to match the 6-source
    # rebalance in DEFAULT_OUTER_WEIGHTS. Only columns that had server_default
    # set need updating (steady_* and liquidation_*); the older columns
    # (trending/ranging/volatile tech/flow/onchain/pattern) never had
    # server_default set, so Postgres uses NULL as default and SQLAlchemy's
    # Python-side default handles new row creation.
    op.alter_column("regime_weights", "steady_tech_weight", server_default="0.36")
    op.alter_column("regime_weights", "steady_flow_weight", server_default="0.16")
    op.alter_column("regime_weights", "steady_onchain_weight", server_default="0.16")
    op.alter_column("regime_weights", "steady_pattern_weight", server_default="0.10")
    op.alter_column("regime_weights", "trending_liquidation_weight", server_default="0.07")
    op.alter_column("regime_weights", "ranging_liquidation_weight", server_default="0.10")
    op.alter_column("regime_weights", "volatile_liquidation_weight", server_default="0.10")


def downgrade() -> None:
    op.alter_column("regime_weights", "steady_tech_weight", server_default="0.48")
    op.alter_column("regime_weights", "steady_flow_weight", server_default="0.22")
    op.alter_column("regime_weights", "steady_onchain_weight", server_default="0.18")
    op.alter_column("regime_weights", "steady_pattern_weight", server_default="0.12")
    op.alter_column("regime_weights", "trending_liquidation_weight", server_default="0.08")
    op.alter_column("regime_weights", "ranging_liquidation_weight", server_default="0.09")
    op.alter_column("regime_weights", "volatile_liquidation_weight", server_default="0.11")
```

- [ ] **Step 4: Run regime, de_sweep, and combiner tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest tests/engine/test_regime.py tests/engine/test_de_sweep.py tests/engine/test_combiner.py -v`
Expected: All PASS

---

### Task 4: Fix SignalDetail.tsx — remove stale confluence_max_score display

The `SnapshotContent` component still references `snapshot.confluence_max_score` which no longer exists in engine snapshots. The confluence score is already displayed in the "Intelligence Components" section (lines 88-90) via `signal.raw_indicators.confluence_score`. The stale snapshot section is dead code that never renders.

**Files:**
- Modify: `web/src/features/signals/components/SignalDetail.tsx:313-318`

- [ ] **Step 1: Remove the stale confluence_max_score section**

Replace lines 313-318:

```tsx
          {/* Confluence */}
          {snapshot.confluence_max_score != null && (
            <SnapGroup title="Confluence">
              <SnapPill label="max score" value={String(snapshot.confluence_max_score)} />
            </SnapGroup>
          )}
```

With (show the actual confluence params from the snapshot if available):

```tsx
          {/* Confluence */}
          {snapshot.confluence != null && (
            <SnapGroup title="Confluence">
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(snapshot.confluence as Record<string, number>).map(([k, v]) => (
                  <SnapPill key={k} label={k.replace(/_/g, " ")} value={typeof v === "number" ? v.toFixed(2) : String(v)} />
                ))}
              </div>
            </SnapGroup>
          )}
```

- [ ] **Step 2: Verify frontend builds**

Run: `cd web && pnpm build`
Expected: Build succeeds with no TypeScript errors

---

### Task 5: Run full test suite and commit

- [ ] **Step 1: Run all backend tests**

Run: `MSYS_NO_PATHCONV=1 docker exec krypton-api-1 python -m pytest -v`
Expected: All PASS

- [ ] **Step 2: Run frontend build**

Run: `cd web && pnpm build`
Expected: Build succeeds

- [ ] **Step 3: Commit all changes**

```bash
git add backend/app/api/routes.py backend/app/engine/optimizer.py backend/app/db/models.py backend/app/db/migrations/versions/b5c6d7e8f9a0_rebalance_regime_outer_weight_defaults.py backend/tests/engine/test_de_sweep.py web/src/features/signals/components/SignalDetail.tsx
git commit -m "fix: confluence redesign cleanup — stale refs, model defaults, keyword args"
```
