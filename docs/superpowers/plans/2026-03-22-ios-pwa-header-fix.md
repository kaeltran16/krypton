# iOS PWA Header Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the EngineHeader conditional so all 5 tabs render the same TickerBar header, eliminating the jarring header swap on the More tab.

**Architecture:** Simplify `Layout.tsx` to always render `<TickerBar>`, then delete `EngineHeader.tsx` (only used by Layout). Two files touched, net negative lines.

**Tech Stack:** React, TypeScript

---

### Task 1: Remove EngineHeader and unify header in Layout

**Files:**
- Delete: `web/src/shared/components/EngineHeader.tsx`
- Modify: `web/src/shared/components/Layout.tsx:1-66`

- [ ] **Step 1: Update Layout.tsx — remove EngineHeader import and conditional**

Remove the `EngineHeader` import (line 4), the `isMarketTab` variable (line 46), and replace the ternary (lines 57-66) with a direct `<TickerBar>` render.

The updated file should have these changes:

```tsx
// Line 4: DELETE this line
import { EngineHeader } from "./EngineHeader";

// Line 46: DELETE this line
const isMarketTab = tab !== "more";

// Lines 57-66: REPLACE the ternary with just TickerBar
// BEFORE:
{isMarketTab ? (
  <TickerBar
    price={price}
    change24h={change24h}
    pair={selectedPair}
    onPairChange={onPairChange}
  />
) : (
  <EngineHeader />
)}

// AFTER:
<TickerBar
  price={price}
  change24h={change24h}
  pair={selectedPair}
  onPairChange={onPairChange}
/>
```

- [ ] **Step 2: Delete EngineHeader.tsx**

```bash
rm web/src/shared/components/EngineHeader.tsx
```

- [ ] **Step 3: Verify build passes**

Run: `cd web && pnpm build`
Expected: Clean build with no errors or warnings about missing EngineHeader

- [ ] **Step 4: Manual verification checklist**

Open the app and verify:
- All 5 tabs show the same TickerBar header (logo + pair picker + price)
- Switching between tabs causes no header flash or layout shift
- iOS PWA (Safari Add to Home Screen): no gap between status bar and header on all 5 tabs
- More tab sub-pages (Engine, Backtest) render correctly below TickerBar via SubPageShell — back-button header not obscured
- No double safe-area padding on any tab
- Desktop/Android: no visual regression — header looks identical

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "fix: unify header across all tabs — remove EngineHeader conditional"
```
