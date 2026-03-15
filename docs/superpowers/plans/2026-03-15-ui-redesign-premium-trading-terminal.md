# UI Redesign: Premium Trading Terminal

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevate Krypton's PWA from a functional dark dashboard to a premium crypto trading terminal through typography upgrade, glassmorphism depth, gradient backgrounds, and meaningful micro-animations.

**Architecture:** Four independent visual layers stacked on the existing component structure — (1) typography tightening (OKX-style Inter usage: tighter tracking, heavier weights, consistent scale), (2) gradient background + transparent layout root, (3) glassmorphism surfaces on nav/modals/ticker, (4) micro-animations via new CSS keyframes + small component edits. No structural component changes, no new dependencies, no new fonts.

**Tech Stack:** React 19, Tailwind CSS 3, CSS keyframes, Google Fonts (Inter, JetBrains Mono — already loaded)

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `web/src/index.css` | Modify | Gradient body bg, glassmorphism utilities, OKX-style type utilities, new keyframes |
| `web/tailwind.config.ts` | Modify | Add new animations/keyframes |
| `web/src/shared/components/Layout.tsx` | Modify | Transparent root bg, glassmorphism nav bar |
| `web/src/shared/components/TickerBar.tsx` | Modify | Glassmorphism ticker bar, OKX-style pair label |
| `web/src/features/home/components/HomeView.tsx` | Modify | OKX-style typography on headers + metrics |
| `web/src/features/signals/components/SignalCard.tsx` | Modify | Pulse glow on pending signals |
| `web/src/features/signals/components/SignalFeed.tsx` | Modify | Wrapper divs with stagger animation on card list |
| `web/src/features/signals/components/ConnectionStatus.tsx` | No change | Connected dot stays solid (stable = static) |
| `web/src/features/trading/components/OrderDialog.tsx` | Modify | Align with global glassmorphism dialog styles |

---

## Task 1: Typography Tightening — OKX-Style Inter

OKX's visual identity comes from how they use their font, not which font it is: heavy weights (700) on key values, tight negative letter-spacing on bold headings, wider tracking on small uppercase labels, and a strict size scale. We already have Inter — we just need to use it like OKX does.

**Files:**
- Modify: `web/src/index.css:1` (add Inter weight 800)
- Modify: `web/src/index.css` (append utility classes)
- Modify: `web/src/features/home/components/HomeView.tsx:59-60,86-89,239-256`
- Modify: `web/src/shared/components/TickerBar.tsx:20,34`

- [ ] **Step 1: Add Inter weight 800 (extrabold) to Google Fonts import**

In `web/src/index.css`, replace line 1:

```css
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500;700&display=swap');
```

Only change: added `800` to Inter's weight list.

- [ ] **Step 2: Add OKX-style typography utility classes**

Append to `web/src/index.css` (after the existing `.animate-slide-down` block):

```css
/* OKX-style typography utilities */
.text-display {
  font-weight: 800;
  letter-spacing: -0.03em;
  line-height: 1.1;
}

.text-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.08em;
}
```

`text-display` — for hero numbers (account equity, performance stats). Extrabold with tight tracking, like OKX's balance display.
`text-label` — for section headers. Semibold (not regular weight) uppercase with wider tracking, matching OKX's category labels. Color is omitted — use `text-muted` alongside `text-label` to stay on the Tailwind semantic color system.

- [ ] **Step 3: Apply text-display to account equity**

In `web/src/features/home/components/HomeView.tsx` line 60, change:
```tsx
<div className="text-2xl font-mono font-bold mt-1">${formatPrice(portfolio.total_equity)}</div>
```
To:
```tsx
<div className="text-2xl font-mono text-display mt-1">${formatPrice(portfolio.total_equity)}</div>
```

Note: Keeps `font-mono` for tabular figures. `text-display` adds the weight (800) and tight tracking (-0.03em) on top.

- [ ] **Step 4: Apply text-label to all section headers**

In `web/src/features/home/components/HomeView.tsx`, replace section header patterns:

Line 59 — change:
```tsx
<div className="text-[10px] text-muted uppercase tracking-wider">Account Balance</div>
```
To:
```tsx
<div className="text-label text-muted">Account Balance</div>
```

Line 118 — change:
```tsx
<span className="text-[10px] text-muted uppercase tracking-wider">
```
To:
```tsx
<span className="text-label text-muted">
```

Line 198 — change:
```tsx
<span className="text-[10px] text-muted uppercase tracking-wider">Latest News</span>
```
To:
```tsx
<span className="text-label text-muted">Latest News</span>
```

Line 239 — change:
```tsx
<div className="text-[10px] text-muted uppercase tracking-wider mb-2">Performance (7D)</div>
```
To:
```tsx
<div className="text-label text-muted mb-2">Performance (7D)</div>
```

- [ ] **Step 5: Apply text-display to performance stats**

In `web/src/features/home/components/HomeView.tsx`, the PerformanceCard values (lines 242, 248, 252) use `text-lg font-mono font-bold`. Change to `text-lg font-mono text-display`:

Line 242 — change:
```tsx
<div className={`text-lg font-mono font-bold ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
```
To:
```tsx
<div className={`text-lg font-mono text-display ${stats.win_rate >= 50 ? "text-long" : "text-short"}`}>
```

Line 248 — change:
```tsx
<div className="text-lg font-mono font-bold">{stats.avg_rr}</div>
```
To:
```tsx
<div className="text-lg font-mono text-display">{stats.avg_rr}</div>
```

Line 252 — change:
```tsx
<div className={`text-lg font-mono font-bold ${netPnl >= 0 ? "text-long" : "text-short"}`}>
```
To:
```tsx
<div className={`text-lg font-mono text-display ${netPnl >= 0 ? "text-long" : "text-short"}`}>
```

- [ ] **Step 6: Apply OKX-style to TickerBar**

In `web/src/shared/components/TickerBar.tsx` line 20, change:
```tsx
className="bg-transparent text-accent font-bold text-sm border-none outline-none appearance-none pr-4"
```
To:
```tsx
className="bg-transparent text-accent font-extrabold text-sm tracking-tight border-none outline-none appearance-none pr-4"
```

Line 34, change:
```tsx
<span className="font-mono font-bold text-sm">${formatPrice(price)}</span>
```
To:
```tsx
<span className="font-mono text-display text-sm">${formatPrice(price)}</span>
```

- [ ] **Step 7: Apply text-label to PortfolioStrip labels**

In `web/src/features/home/components/HomeView.tsx`, the PortfolioStrip metric labels (lines 89, 93, 97, 103) use `text-[10px] text-muted uppercase`. Change each to `text-label`:

Line 89: `<div className="text-[10px] text-muted uppercase">Unrealized</div>` → `<div className="text-label text-muted">Unrealized</div>`
Line 93: `<div className="text-[10px] text-muted uppercase">Available</div>` → `<div className="text-label text-muted">Available</div>`
Line 97: `<div className="text-[10px] text-muted uppercase">Margin</div>` → `<div className="text-label text-muted">Margin</div>`
Line 103: `<div className="text-[10px] text-muted uppercase">Exposure</div>` → `<div className="text-label text-muted">Exposure</div>`

Note: These labels previously had no explicit `letter-spacing`. `text-label` adds `0.08em` tracking. Verify at 375px that the 4-column grid labels don't overflow with the wider spacing.

- [ ] **Step 8: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build. Hero numbers feel heavier and tighter (OKX-like). Labels are sharper with semibold weight. No font changes — same Inter + JetBrains Mono, just used with more intention.

---

## Task 2: Gradient Background + Transparent Layout Root

**Files:**
- Modify: `web/src/index.css:12-20`
- Modify: `web/src/shared/components/Layout.tsx:28`

- [ ] **Step 1: Replace flat body background with subtle gradient**

In `web/src/index.css`, replace the `body` rule (lines 12-20):

```css
body {
  background: linear-gradient(180deg, #0d1117 0%, #0B0E11 40%, #080a0e 100%);
  color: #EAECEF;
  font-family: Inter, system-ui, -apple-system, sans-serif;
  margin: 0;
  min-height: 100vh;
  min-height: 100dvh;
  -webkit-font-smoothing: antialiased;
  -webkit-tap-highlight-color: transparent;
  overscroll-behavior: none;
}
```

Note: Uses `min-height: 100dvh` (with `100vh` fallback) instead of `background-attachment: fixed` because `background-attachment: fixed` is broken on iOS Safari. The gradient naturally covers the viewport since body fills the screen. No scroll attachment needed for a top-to-bottom gradient on a full-height body.

- [ ] **Step 2: Make Layout root transparent so gradient shows through**

In `web/src/shared/components/Layout.tsx` line 28, change:
```tsx
<div className="min-h-screen bg-surface text-foreground flex flex-col">
```
To:
```tsx
<div className="min-h-screen min-h-dvh text-foreground flex flex-col">
```

**Critical:** Remove `bg-surface`. The Layout root sits between `body` (gradient) and the nav/ticker (glassmorphism). If this remains opaque, `backdrop-blur` on nav/ticker will blur a flat color — making glassmorphism invisible. The body gradient must show through.

- [ ] **Step 3: Verify on mobile viewport**

Run: `cd web && pnpm dev`
Check at 375px width: gradient visible behind cards, no banding artifacts, cards (`bg-card`) still visually distinct from background.

---

## Task 3: Glassmorphism — Nav Bar, Ticker Bar, Dialogs

**Files:**
- Modify: `web/src/shared/components/Layout.tsx:36`
- Modify: `web/src/shared/components/TickerBar.tsx:15`
- Modify: `web/src/index.css:26-42`
- Modify: `web/src/features/trading/components/OrderDialog.tsx:89`

- [ ] **Step 1: Upgrade nav bar glassmorphism**

In `web/src/shared/components/Layout.tsx` line 36, change:
```tsx
<nav className="fixed bottom-0 left-0 right-0 bg-card/95 backdrop-blur-md border-t border-border flex safe-bottom z-30">
```
To:
```tsx
<nav className="fixed bottom-0 left-0 right-0 bg-card/80 backdrop-blur-xl border-t border-white/[0.06] flex safe-bottom z-30">
```

Changes: `bg-card/95` → `bg-card/80` (more transparent), `backdrop-blur-md` → `backdrop-blur-xl` (stronger blur), `border-border` → `border-white/[0.06]` (subtle light edge).

- [ ] **Step 2: Upgrade ticker bar glassmorphism**

In `web/src/shared/components/TickerBar.tsx` line 15, change:
```tsx
<div className="sticky top-0 z-30 bg-card border-b border-border safe-top">
```
To:
```tsx
<div className="sticky top-0 z-30 bg-card/80 backdrop-blur-xl border-b border-white/[0.06] safe-top">
```

- [ ] **Step 3: Upgrade global dialog glassmorphism**

In `web/src/index.css`, replace the `dialog::backdrop` and `dialog` rules (lines 26-42):

```css
dialog::backdrop {
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

dialog {
  margin: 0;
  margin-top: auto;
  padding: 0;
  border: none;
  max-height: 85vh;
  width: 100%;
  max-width: 32rem;
  border-radius: 1rem 1rem 0 0;
  overflow-y: auto;
  background: rgba(18, 22, 28, 0.9);
  backdrop-filter: blur(20px);
  -webkit-backdrop-filter: blur(20px);
  color: #EAECEF;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
```

- [ ] **Step 4: Align OrderDialog with global dialog styles**

`OrderDialog.tsx` line 89 has inline Tailwind classes that override the global `dialog` CSS (the `bg-card` class produces an opaque background, and `backdrop:bg-black/60` conflicts with the global `dialog::backdrop` rule).

In `web/src/features/trading/components/OrderDialog.tsx` line 89, change:
```tsx
className="bg-card text-white rounded-xl w-full max-w-md border border-gray-800 backdrop:bg-black/60"
```
To:
```tsx
className="text-white w-full max-w-md"
```

The global `dialog` rule in `index.css` now handles background, border, border-radius, and backdrop styling. Remove the inline overrides so OrderDialog gets the same glassmorphism treatment. The `rounded-xl` is replaced by the global `border-radius: 1rem 1rem 0 0`. The `border-gray-800` is replaced by the global `border-top: 1px solid rgba(255, 255, 255, 0.06)`.

Also update the inner border dividers to use the `border-border` token instead of `border-gray-800`. Lines 90, 193:

Line 90 — change:
```tsx
<div className="p-4 border-b border-gray-800">
```
To:
```tsx
<div className="p-4 border-b border-border">
```

Line 193 — change:
```tsx
<div className="p-4 border-t border-gray-800">
```
To:
```tsx
<div className="p-4 border-t border-border">
```

- [ ] **Step 5: Build and verify**

Run: `cd web && pnpm build`
Expected: Clean build. Nav bar and ticker blur content behind them when scrolling. Dialogs (indicator sheet, order dialog) have frosted glass appearance.

---

## Task 4: Micro-Animations — Signal Pulse + Card Entry

**Files:**
- Modify: `web/tailwind.config.ts:10-19`
- Modify: `web/src/index.css` (append)
- Modify: `web/src/features/signals/components/SignalCard.tsx:21`
- Modify: `web/src/features/signals/components/SignalFeed.tsx:56-65`

- [ ] **Step 1: Add new animation keyframes to Tailwind config**

In `web/tailwind.config.ts`, replace the `animation` and `keyframes` blocks (lines 10-19):

```typescript
animation: {
  'slide-down': 'slideDown 0.3s ease-out',
  'slide-up': 'slideUp 0.3s ease-out',
  'fade-in': 'fadeIn 0.15s ease-in-out',
  'card-enter': 'cardEnter 0.35s cubic-bezier(0.16, 1, 0.3, 1) backwards',
  'pulse-glow': 'pulseGlow 2s ease-in-out infinite',
},
keyframes: {
  slideDown: { '0%': { transform: 'translateY(-100%)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
  slideUp: { '0%': { transform: 'translateY(20px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
  fadeIn: { '0%': { opacity: '0' }, '100%': { opacity: '1' } },
  cardEnter: { '0%': { transform: 'translateY(12px)', opacity: '0' }, '100%': { transform: 'translateY(0)', opacity: '1' } },
  pulseGlow: { '0%, 100%': { boxShadow: '0 0 0 0 rgba(240, 185, 11, 0)' }, '50%': { boxShadow: '0 0 8px 2px rgba(240, 185, 11, 0.15)' } },
},
```

Note: `card-enter` uses `backwards` fill-mode, meaning elements hold the `from` keyframe (`opacity: 0; translateY(12px)`) during their stagger delay, then animate to their natural visible state. After animation completes, elements revert to normal CSS (fully visible) — so cards won't get stuck invisible if anything goes wrong. The stagger classes in Step 2 and the wrapper divs in Step 4 are tightly coupled — implement Steps 1, 2, and 4 together, then verify.

- [ ] **Step 2: Add stagger delay CSS utility**

Append to `web/src/index.css`:

```css
/* Stagger animation delays for card lists */
.stagger-1 { animation-delay: 0ms; }
.stagger-2 { animation-delay: 40ms; }
.stagger-3 { animation-delay: 80ms; }
.stagger-4 { animation-delay: 120ms; }
.stagger-5 { animation-delay: 160ms; }
.stagger-6 { animation-delay: 200ms; }
.stagger-7 { animation-delay: 240ms; }
.stagger-8 { animation-delay: 280ms; }
.stagger-9 { animation-delay: 320ms; }
.stagger-10 { animation-delay: 360ms; }
```

- [ ] **Step 3: Add pulse glow to pending signal cards**

In `web/src/features/signals/components/SignalCard.tsx` line 21, change:
```tsx
className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}`}
```
To:
```tsx
className={`w-full p-3 rounded-lg border text-left transition-colors active:opacity-80 ${borderColor} ${bgColor}${isPending ? " animate-pulse-glow" : ""}`}
```

- [ ] **Step 4: Add staggered entry animation to signal feed**

In `web/src/features/signals/components/SignalFeed.tsx`, replace lines 56-65 (the filtered card rendering block):

Current code:
```tsx
<div className="space-y-2">
  {filtered.map((signal) => (
    <SignalCard
      key={signal.id}
      signal={signal}
      onSelect={selectSignal}
      onExecute={setTradingSignal}
    />
  ))}
</div>
```

Replace with:
```tsx
<div className="space-y-2">
  {filtered.map((signal, i) => (
    <div key={signal.id} className={`animate-card-enter stagger-${Math.min(i + 1, 10)}`}>
      <SignalCard
        signal={signal}
        onSelect={selectSignal}
        onExecute={setTradingSignal}
      />
    </div>
  ))}
</div>
```

Changes: (1) Added `i` index parameter to `.map()`, (2) wrapped each `<SignalCard>` in a `<div>` with animation classes, (3) moved `key` to the wrapper div.

- [ ] **Step 5: Add `prefers-reduced-motion` override**

Append to `web/src/index.css`:

```css
/* Respect reduced-motion preferences (WCAG 2.1) */
@media (prefers-reduced-motion: reduce) {
  .animate-card-enter { animation: none !important; opacity: 1; transform: none; }
  .animate-pulse-glow { animation: none !important; }
}
```

This disables stagger and pulse animations for users with motion sensitivity. The `!important` is needed to override Tailwind's `animate-*` utility classes.

- [ ] **Step 6: Build and verify animations**

Run: `cd web && pnpm build`
Expected: Clean build. Then `pnpm dev` — signal cards stagger in on load, pending signals have subtle gold glow pulse. Connection status dot remains unchanged (solid when connected, pulses when disconnected).

---

## Task 5: Polish Pass — Glass Cards on Dashboard

**Files:**
- Modify: `web/src/index.css` (append)
- Modify: `web/src/features/home/components/HomeView.tsx:56,238`

- [ ] **Step 1: Add a glass-card utility class**

Append to `web/src/index.css`:

```css
/* Elevated glass card — use on primary dashboard cards for visual hierarchy */
.glass-card {
  background: rgba(18, 22, 28, 0.65);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-radius: 0.5rem;
}
```

Note: Includes `backdrop-filter: blur(12px)` so the gradient background blurs through. Without it, the semi-transparent background would just show gradient color bleed (not frosted glass). Only use this on the top-tier dashboard cards (AccountHeader, PerformanceCard) — do NOT replace every `bg-card` in the app.

- [ ] **Step 2: Apply glass-card to AccountHeader**

In `web/src/features/home/components/HomeView.tsx` line 56, change:
```tsx
<div className="bg-card rounded-lg p-4 border border-border">
```
To:
```tsx
<div className="glass-card p-4">
```

- [ ] **Step 3: Apply glass-card to PerformanceCard**

In `web/src/features/home/components/HomeView.tsx` line 238, change:
```tsx
<div className="bg-card rounded-lg p-3 border border-border">
```
To:
```tsx
<div className="glass-card p-3">
```

- [ ] **Step 4: Final build verification**

Run: `cd web && pnpm build`
Expected: Clean build. AccountHeader and Performance cards show subtle frosted glass effect against the gradient background.

---

## Task 6: Smoke Test All Views

- [ ] **Step 1: Run full build**

Run: `cd web && pnpm build`
Expected: Zero errors.

- [ ] **Step 2: Run tests**

Run: `cd web && pnpm test`
Expected: All existing tests pass.

- [ ] **Step 3: Visual verification checklist**

Open `pnpm dev` and verify each tab at 375px width:

- [ ] **Home tab:** Gradient background visible through transparent layout root. AccountHeader and PerformanceCard have frosted glass effect. Section labels use semibold uppercase with wider tracking (`text-label`). Hero numbers (equity, stats) feel heavier with tight tracking (`text-display`). All numeric values remain in monospace.
- [ ] **Chart tab:** No regressions — chart renders correctly against gradient background.
- [ ] **Signals tab:** Cards stagger in with 40ms delays on load. Pending signals pulse with subtle gold glow. Closed signals do NOT pulse. Filter button changes re-trigger stagger animation.
- [ ] **News tab:** No regressions.
- [ ] **More tab:** No regressions.
- [ ] **Nav bar:** Content blurs through when scrolling (verify glassmorphism is visible, not just a flat color).
- [ ] **Ticker bar:** Content blurs through when scrolling.
- [ ] **Order Dialog:** Opens with frosted glass appearance, consistent with indicator sheet and other dialogs.
- [ ] **Connection dot:** Solid green when connected, pulses red when disconnected (unchanged behavior).
- [ ] **Reduced motion:** Enable "Reduce motion" in OS accessibility settings (or Chrome DevTools → Rendering → Emulate CSS media feature `prefers-reduced-motion`). Verify: no card stagger, no pulse glow. Cards appear immediately.
- [ ] **Performance:** In Chrome DevTools → Performance tab, enable 4x CPU slowdown. Scroll the Home tab — verify no frame drops from stacked `backdrop-filter` layers (ticker + glass-card + nav). If janky, remove `backdrop-filter` from `.glass-card` first (it's the least impactful since only 2 cards use it).
