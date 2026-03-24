# Settings Page Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the Settings page to match the visual quality of other redesigned pages (Risk, ML Training, System Diagnostics) — unified pill buttons, styled slider, card-per-setting layout, remove redundant System section.

**Architecture:** Pure UI rewrite of `SettingsPage.tsx` with no store/type changes. Each setting gets its own card container (matching `RiskSection` styling). All multi-select buttons use a single unified pill style. Range slider gets custom CSS track/thumb. `SettingsGroup.tsx` is deleted. `QuietHoursSettings.tsx` gets a label styling tweak.

**Tech Stack:** React, Tailwind CSS v3, existing Zustand store (unchanged)

---

### Task 1: Add Custom Range Slider CSS

**Files:**
- Modify: `web/src/index.css` (append after existing styles)

- [ ] **Step 1: Add range slider styles to index.css**

Append the following CSS at the end of `web/src/index.css` (before the closing `@media (prefers-reduced-motion)` block):

```css
/* Custom range slider — Settings threshold */
input[type="range"].styled-range {
  -webkit-appearance: none;
  appearance: none;
  width: 100%;
  height: 6px;
  background: var(--color-surface-container-lowest, #0d1117);
  border-radius: 3px;
  outline: none;
}

input[type="range"].styled-range::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-primary);
  cursor: pointer;
  box-shadow: 0 0 8px rgba(105, 218, 255, 0.4);
}

input[type="range"].styled-range::-moz-range-thumb {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: var(--color-primary);
  border: none;
  cursor: pointer;
  box-shadow: 0 0 8px rgba(105, 218, 255, 0.4);
}

input[type="range"].styled-range::-moz-range-track {
  height: 6px;
  background: var(--color-surface-container-lowest, #0d1117);
  border-radius: 3px;
}
```

Note: The CSS variable `--color-primary` is already defined in `:root` as `#69daff`. For `--color-surface-container-lowest`, we use the hardcoded fallback `#0d1117` since this token is defined in JS theme but not as a CSS variable. This is consistent with other components that use Tailwind classes for these colors.

- [ ] **Step 2: Verify visually** (build check happens in Task 4)

---

### Task 2: Rewrite SettingsPage.tsx

**Files:**
- Rewrite: `web/src/features/settings/components/SettingsPage.tsx`

This is the core task. The new file removes the System section, removes `SettingsGroup` usage, replaces all button styles with unified pills, wraps each setting in its own card, adds section labels, and uses the styled range slider.

- [ ] **Step 1: Write the new SettingsPage.tsx**

Replace the entire file with:

```tsx
import { useState } from "react";
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";
import type { Timeframe } from "../../signals/types";
import { QuietHoursSettings } from "../../alerts/components/QuietHoursSettings";
import { Toggle } from "../../../shared/components/Toggle";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

function toggleItem<T>(list: T[], item: T, minOne = true): T[] {
  if (list.includes(item)) {
    if (minOne && list.length <= 1) return list;
    return list.filter((i) => i !== item);
  }
  return [...list, item];
}

/* ── Shared card container (matches RiskSection without status icon) ── */

function SettingsCard({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
      <h3 className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant mb-3">
        {title}
      </h3>
      {children}
    </section>
  );
}

/* ── Unified pill button row ── */

function PillSelect<T extends string | number>({
  options,
  selected,
  onToggle,
  multi = false,
  renderLabel,
}: {
  options: T[];
  selected: T | T[];
  onToggle: (value: T) => void;
  multi?: boolean;
  renderLabel?: (value: T) => string;
}) {
  const isActive = (v: T) =>
    multi ? (selected as T[]).includes(v) : selected === v;

  return (
    <div className="flex gap-3">
      {options.map((opt) => (
        <button
          key={String(opt)}
          onClick={() => onToggle(opt)}
          className={`flex-1 min-h-[44px] py-2 text-sm font-medium rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-primary focus-visible:outline-none ${
            isActive(opt)
              ? "bg-primary/15 text-primary border border-primary/30 font-bold"
              : "bg-surface-container-lowest text-on-surface-variant"
          }`}
        >
          {renderLabel ? renderLabel(opt) : String(opt)}
        </button>
      ))}
    </div>
  );
}

/* ── Section label ── */

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-[10px] font-bold text-primary uppercase tracking-widest opacity-80 px-1 mb-2">
      {children}
    </h2>
  );
}

/* ── Main page ── */

export default function SettingsPage() {
  const {
    pairs, timeframes, threshold, notificationsEnabled,
    onchainEnabled, newsAlertsEnabled, newsContextWindow,
    loading, syncError,
    setPairs, setTimeframes, setThreshold, setNotificationsEnabled,
    setOnchainEnabled, setNewsAlertsEnabled, setNewsContextWindow,
  } = useSettingsStore();
  const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");

  async function handleNotificationToggle(enabled: boolean) {
    setNotificationsEnabled(enabled);
    if (enabled) {
      setPushStatus("subscribing");
      const ok = await subscribeToPush(pairs, timeframes, threshold);
      setPushStatus(ok ? "idle" : "error");
      if (!ok) setNotificationsEnabled(false);
    } else {
      await unsubscribeFromPush();
    }
  }

  if (loading) {
    return (
      <div className="p-3 space-y-3">
        <div className="h-28 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-20 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
        <div className="h-24 bg-surface-container rounded-lg animate-pulse motion-reduce:animate-none border border-outline-variant/10" />
      </div>
    );
  }

  return (
    <div className="p-3 space-y-3">
      {syncError && (
        <div role="alert" className="bg-error/10 border border-error/30 rounded-lg px-3 py-2 text-xs text-error">
          Settings sync failed — changes may not be saved
        </div>
      )}

      {/* ── Trading ── */}
      <SectionLabel>Trading</SectionLabel>

      <SettingsCard title="Pairs">
        <PillSelect
          options={AVAILABLE_PAIRS as unknown as string[]}
          selected={pairs}
          onToggle={(pair) => setPairs(toggleItem(pairs, pair))}
          multi
          renderLabel={(pair) => pair.replace("-USDT-SWAP", "")}
        />
      </SettingsCard>

      <SettingsCard title="Timeframes">
        <PillSelect
          options={TIMEFRAMES}
          selected={timeframes}
          onToggle={(tf) => setTimeframes(toggleItem(timeframes, tf))}
          multi
        />
      </SettingsCard>

      <SettingsCard title="Signal Threshold">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs text-on-surface-variant">Minimum score to trigger a signal</span>
          <span className="font-headline text-2xl font-bold tabular-nums text-primary">{threshold}</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="styled-range w-full"
          aria-label="Signal threshold"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={threshold}
        />
        <div className="flex justify-between text-[10px] font-mono text-outline mt-1.5">
          <span>0</span>
          <span>100</span>
        </div>
      </SettingsCard>

      <SettingsCard title="On-Chain Scoring">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] text-on-surface-variant mt-0.5">Blend exchange flows and whale metrics</p>
          </div>
          <Toggle checked={onchainEnabled} onChange={setOnchainEnabled} />
        </div>
      </SettingsCard>

      <SettingsCard title="News Alerts">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[11px] text-on-surface-variant mt-0.5">Push for high-impact news</p>
          </div>
          <Toggle checked={newsAlertsEnabled} onChange={setNewsAlertsEnabled} />
        </div>
      </SettingsCard>

      <SettingsCard title="LLM News Window">
        <PillSelect
          options={[15, 30, 60]}
          selected={newsContextWindow}
          onToggle={(mins) => setNewsContextWindow(mins)}
          renderLabel={(mins) => `${mins}m`}
        />
      </SettingsCard>

      {/* ── Notifications ── */}
      <SectionLabel>Notifications</SectionLabel>

      <SettingsCard title="Push Notifications">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm text-on-surface">Enable push notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-error mt-0.5">Permission denied</p>
            )}
          </div>
          <Toggle
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={(v) => handleNotificationToggle(v)}
          />
        </div>
      </SettingsCard>

      <section className="bg-surface-container border border-outline-variant/10 rounded-lg p-4">
        <QuietHoursSettings />
      </section>
    </div>
  );
}
```

Key changes from current implementation:
- **Removed:** `useSignalStore` import, `PAIR_NAMES` map, `SettingsGroup` import, `apiBaseUrl`/`setApiBaseUrl` destructuring, entire System section
- **Added:** `SettingsCard` local component (card container), `PillSelect` local component (unified pill buttons), `SectionLabel` local component
- **Slider:** Uses `className="styled-range"` (Task 1 CSS) + ARIA attributes
- **Sync error banner:** Added `role="alert"` for screen reader announcement (spec requirement)
- **Quiet Hours card:** No title — wraps `QuietHoursSettings` in a bare card container since the component renders its own label

- [ ] **Step 2: Run TypeScript check**

Run: `cd web && npx tsc --noEmit`
Expected: No errors. This confirms all imports resolve and types are correct.

- [ ] **Step 3: Run existing store tests**

Run: `cd web && npx vitest run src/features/settings/store.test.ts`
Expected: All 5 tests PASS (unchanged store behavior).

---

### Task 3: Update QuietHoursSettings Label

**Files:**
- Modify: `web/src/features/alerts/components/QuietHoursSettings.tsx:42-43`

- [ ] **Step 1: Update the label styling**

In `QuietHoursSettings.tsx`, change line 43 from:

```tsx
        <span className="text-sm text-on-surface">Quiet Hours</span>
```

to:

```tsx
        <span className="font-headline text-[10px] font-black uppercase tracking-[0.2em] text-on-surface-variant">Quiet Hours</span>
```

This makes the component's internal "Quiet Hours" label match the `SettingsCard` title pattern so it looks consistent when rendered inside the bare card container (no duplicate title).

- [ ] **Step 2: Verify build**

Run: `cd web && npx tsc --noEmit`
Expected: No errors.

---

### Task 4: Delete SettingsGroup.tsx

**Files:**
- Delete: `web/src/features/settings/components/SettingsGroup.tsx`

- [ ] **Step 1: Verify no remaining imports**

Run: `cd web && grep -r "SettingsGroup" src/`
Expected: Zero matches. The only consumer was `SettingsPage.tsx` which was rewritten in Task 2.

- [ ] **Step 2: Delete the file**

```bash
rm web/src/features/settings/components/SettingsGroup.tsx
```

- [ ] **Step 3: Run full build**

Run: `cd web && pnpm build`
Expected: Build succeeds with no errors. This is the definitive check — TypeScript compilation + Vite bundling.

- [ ] **Step 4: Run all frontend tests**

Run: `cd web && npx vitest run`
Expected: All tests pass. This confirms the store tests still pass and no other test imports `SettingsGroup`.

---

### Task 5: Final Verification

- [ ] **Step 1: Run full build one more time**

Run: `cd web && pnpm build`
Expected: Clean build, no warnings about unused imports or missing modules.

- [ ] **Step 2: Run all frontend tests**

Run: `cd web && npx vitest run`
Expected: All tests pass.

- [ ] **Step 3: Start dev server and manual check**

Run: `cd web && pnpm dev`

Manual verification checklist:
- [ ] 8 settings cards render (Pairs, Timeframes, Signal Threshold, On-Chain Scoring, News Alerts, LLM News Window, Push Notifications, Quiet Hours)
- [ ] "Trading" and "Notifications" section labels show in primary color, uppercase
- [ ] Pill buttons for Pairs show BTC / ETH / WIF (no full coin names)
- [ ] Pill buttons use unified active/inactive styling across all three pill groups
- [ ] Range slider has custom styled track (dark) and thumb (primary with glow)
- [ ] Threshold large value display updates as slider moves
- [ ] Toggle switches work for On-Chain, News Alerts, Push Notifications
- [ ] Quiet Hours toggle expands start/end/timezone fields
- [ ] No System section visible (API endpoint, version, connection status are gone)
- [ ] Sync error banner appears with `role="alert"` if sync fails
- [ ] Loading skeleton shows pulse animation on initial load

- [ ] **Step 4: Commit all changes**

```bash
git add -A
git commit -m "feat: settings page redesign — card layout, unified pills, styled slider, remove System section"
```
