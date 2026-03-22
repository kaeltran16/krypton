# iOS PWA Header Fix + Consistent Header

**Date:** 2026-03-22

## Problem

1. **Inconsistent header:** The "More" tab renders `EngineHeader` ("Engine Control" with terminal icon) instead of the `TickerBar` used by the other 4 tabs. This causes a jarring visual swap when switching tabs — violating navigation consistency (the header should remain stable across all tabs).

## Non-issues (investigated and ruled out)

- **iOS PWA safe-area gap:** Both `TickerBar` and `EngineHeader` already apply the `safe-top` class, and their `bg-surface` background fills the padding area behind the status bar. The combination of `viewport-fit=cover` + `black-translucent` + `safe-top` is correct. No CSS changes needed.
- **SubPageShell notch overlap:** `SubPageShell` renders inside the `<main>` scroll area in `Layout.tsx`, which is a flex sibling *below* the header. The header (TickerBar) already handles safe-area padding, so SubPageShell's back-button header never overlaps the notch. Adding `safe-top` to SubPageShell would create double safe-area padding. No changes needed.

## Solution

### 1. Unified TickerBar on all tabs

Remove the `isMarketTab` conditional in `Layout.tsx` so all 5 tabs render the same `TickerBar` header (logo + pair picker + price). Delete `EngineHeader.tsx` — the MorePage already has its own "System Hub" title in the content body.

**File:** `web/src/shared/components/Layout.tsx`
- Remove `isMarketTab` variable (line 46)
- Remove the ternary that switches between `TickerBar` and `EngineHeader` (lines 57-66)
- Always render `<TickerBar>`
- Remove `EngineHeader` import (line 4)

**File:** `web/src/shared/components/EngineHeader.tsx`
- Delete this file (only consumed by `Layout.tsx`)

## Files Changed

| File | Action |
|------|--------|
| `web/src/shared/components/Layout.tsx` | Remove EngineHeader conditional, always render TickerBar |
| `web/src/shared/components/EngineHeader.tsx` | Delete |

## Testing

- Tab switching: verify header remains stable (TickerBar with logo + pair picker + price) when cycling through all 5 tabs including More
- iOS PWA (Safari Add to Home Screen): verify no gap between status bar and header on all 5 tabs
- iOS PWA: verify SubPageShell sub-pages (Engine, Backtest, etc.) render correctly below the TickerBar with no double safe-area padding
- Desktop/Android: verify no visual regression — header should look identical
- More tab sub-pages: verify back-button header in SubPageShell is not obscured by the TickerBar above it
