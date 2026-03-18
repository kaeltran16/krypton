# Vite PWA Improvements Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the iOS install experience (proper icons, splash screens) and add an app update modal so users know when a new version is available.

**Architecture:** Enhance the existing `vite-plugin-pwa` `injectManifest` setup. Switch `registerType` to `"prompt"` so the plugin exposes update hooks instead of auto-activating. Add a `useServiceWorker` hook using `virtual:pwa-register` and a simple `UpdateModal` component. iOS meta tags and splash screens are purely static additions to `index.html` and `public/`.

**Tech Stack:** React 19, TypeScript, vite-plugin-pwa 1.2.0, Tailwind CSS 3

**Spec:** `docs/superpowers/specs/2026-03-17-vite-pwa-improvements-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `web/public/apple-touch-icon-180.png` | **Create** | 180x180 iOS standard touch icon |
| `web/public/icon-512-maskable.png` | **Create** | 512x512 maskable icon with safe zone padding |
| `web/public/apple-splash-*.png` (11 files) | **Create** | iOS splash screen images per device size |
| `web/index.html` | **Modify** | Update theme-color, apple-touch-icon, add splash screen link tags |
| `web/vite.config.ts` | **Modify** | Change registerType, update colors, add maskable icon, narrow globPatterns |
| `web/src/sw.ts` | **Modify** | Add SKIP_WAITING message handler |
| `web/tsconfig.app.json` | **Modify** | Add `vite-plugin-pwa/client` to types array |
| `web/src/shared/hooks/useServiceWorker.ts` | **Create** | SW registration via plugin + update detection hook |
| `web/src/shared/hooks/useServiceWorker.test.ts` | **Create** | Tests for SW update detection hook |
| `web/src/shared/components/UpdateModal.tsx` | **Create** | Modal UI using native `<dialog>` for "Update Now" / "Later" |
| `web/src/App.tsx` | **Modify** | Wire in useServiceWorker + UpdateModal |

---

## Task 1: Generate icon assets

**Files:**
- Create: `web/public/apple-touch-icon-180.png`
- Create: `web/public/icon-512-maskable.png`

The existing `icon-512.png` is the source. We need two derivatives.

- [ ] **Step 1: Generate 180x180 apple-touch-icon**

Using Node.js canvas or a CLI tool, resize `icon-512.png` to 180x180. If no image tool is available, use a simple HTML canvas script:

```bash
cd web
node -e "
const { createCanvas, loadImage } = require('canvas');
// If canvas not available, use sharp or manual creation
"
```

Alternatively, since this is a simple resize + a maskable variant, create them using the `sharp` package as a one-off script:

```bash
cd web
npx sharp-cli resize 180 180 -i public/icon-512.png -o public/apple-touch-icon-180.png
```

If CLI tools aren't available, manually create the PNGs using any image editor. The key requirements:
- `apple-touch-icon-180.png`: 180x180, no padding, the app icon fills the canvas
- `icon-512-maskable.png`: 512x512, with the icon centered in the inner 80% safe zone (40px padding on each side at 512px = icon drawn at 410x410 centered)

- [ ] **Step 2: Verify both files exist and are valid PNGs**

```bash
ls -la web/public/apple-touch-icon-180.png web/public/icon-512-maskable.png
file web/public/apple-touch-icon-180.png web/public/icon-512-maskable.png
```

Expected: Both files exist, both identified as PNG image data.

---

## Task 2: Generate splash screen images

**Files:**
- Create: 11 PNG files in `web/public/`

- [ ] **Step 1: Create a Node script to generate all splash screens**

Create a temporary script `web/generate-splash.mjs` that generates dark background images with the icon centered. Each image: `#0B0E11` background, the app icon centered at ~20% of the shortest dimension.

The 11 required sizes (portrait only):

| Filename | Width | Height |
|----------|-------|--------|
| `apple-splash-750x1334.png` | 750 | 1334 |
| `apple-splash-1242x2208.png` | 1242 | 2208 |
| `apple-splash-1125x2436.png` | 1125 | 2436 |
| `apple-splash-828x1792.png` | 828 | 1792 |
| `apple-splash-1242x2688.png` | 1242 | 2688 |
| `apple-splash-1170x2532.png` | 1170 | 2532 |
| `apple-splash-1179x2556.png` | 1179 | 2556 |
| `apple-splash-1290x2796.png` | 1290 | 2796 |
| `apple-splash-1206x2622.png` | 1206 | 2622 |
| `apple-splash-1320x2868.png` | 1320 | 2868 |
| `apple-splash-1080x2340.png` | 1080 | 2340 |

```js
// web/generate-splash.mjs
import sharp from "sharp";
import { join } from "path";

const SIZES = [
  [750, 1334], [1242, 2208], [1125, 2436], [828, 1792],
  [1242, 2688], [1170, 2532], [1179, 2556], [1290, 2796],
  [1206, 2622], [1320, 2868], [1080, 2340],
];

const BG_COLOR = { r: 11, g: 14, b: 17, alpha: 1 }; // #0B0E11

const icon = sharp("public/icon-512.png");
const iconMeta = await icon.metadata();

for (const [w, h] of SIZES) {
  const iconSize = Math.round(Math.min(w, h) * 0.2);
  const resizedIcon = await icon.resize(iconSize, iconSize).png().toBuffer();

  await sharp({
    create: { width: w, height: h, channels: 4, background: BG_COLOR },
  })
    .composite([{
      input: resizedIcon,
      left: Math.round((w - iconSize) / 2),
      top: Math.round((h - iconSize) / 2),
    }])
    .png()
    .toFile(join("public", `apple-splash-${w}x${h}.png`));

  console.log(`Generated apple-splash-${w}x${h}.png`);
}
```

- [ ] **Step 2: Install sharp (if needed) and run the script**

```bash
cd web
node -e "require('sharp')" 2>/dev/null || pnpm add -D sharp
node generate-splash.mjs
```

- [ ] **Step 3: Verify all 11 splash files exist**

```bash
ls -la web/public/apple-splash-*.png | wc -l
```

Expected: 11 files.

- [ ] **Step 4: Clean up the generator script and sharp dependency**

```bash
rm web/generate-splash.mjs
cd web && pnpm remove sharp  # only if it was added in step 2
```

---

## Task 3: Update vite.config.ts

**Files:**
- Modify: `web/vite.config.ts`

- [ ] **Step 1: Change registerType from "autoUpdate" to "prompt"**

In `web/vite.config.ts`, change line 13:
```ts
    registerType: "autoUpdate",
```
to:
```ts
    registerType: "prompt",
```

- [ ] **Step 2: Update manifest theme_color and background_color**

Change lines 18-19:
```ts
      theme_color: "#121212",
      background_color: "#121212",
```
to:
```ts
      theme_color: "#0B0E11",
      background_color: "#0B0E11",
```

- [ ] **Step 3: Add maskable icon to manifest icons array**

Change lines 22-24:
```ts
        { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
```
to:
```ts
        { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
        { src: "/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
```

- [ ] **Step 4: Narrow globPatterns to exclude splash screens**

Change line 27:
```ts
      globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
```
to:
```ts
      globPatterns: ["**/*.{js,css,html,ico,svg}", "icon-*.png", "apple-touch-icon-*.png"],
```

- [ ] **Step 5: Verify the build still works**

```bash
cd web && pnpm build
```

Expected: Build succeeds. Check `dist/manifest.webmanifest` contains the maskable icon and updated colors.

---

## Task 4: Update index.html

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Update theme-color meta tag**

Change line 6:
```html
    <meta name="theme-color" content="#121212" />
```
to:
```html
    <meta name="theme-color" content="#0B0E11" />
```

- [ ] **Step 2: Update apple-touch-icon**

Change line 11:
```html
    <link rel="icon" type="image/png" href="/icon-192.png" />
    <link rel="apple-touch-icon" href="/icon-192.png" />
```
to:
```html
    <link rel="icon" type="image/png" href="/icon-192.png" />
    <link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-180.png" />
```

- [ ] **Step 3: Add all splash screen link tags**

Add the following after the apple-touch-icon line (before `</head>`):

```html
    <link rel="apple-touch-startup-image" href="/apple-splash-750x1334.png" media="(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1242x2208.png" media="(device-width: 414px) and (device-height: 736px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1125x2436.png" media="(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-828x1792.png" media="(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1242x2688.png" media="(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1170x2532.png" media="(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1179x2556.png" media="(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1290x2796.png" media="(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1206x2622.png" media="(device-width: 402px) and (device-height: 874px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1320x2868.png" media="(device-width: 440px) and (device-height: 956px) and (-webkit-device-pixel-ratio: 3)" />
    <link rel="apple-touch-startup-image" href="/apple-splash-1080x2340.png" media="(device-width: 360px) and (device-height: 780px) and (-webkit-device-pixel-ratio: 3)" />
```

The media queries use CSS points (pixel size / device-pixel-ratio):
- 750x1334 @2x = 375x667 points
- 1242x2208 @3x = 414x736 points
- 1125x2436 @3x = 375x812 points
- 828x1792 @2x = 414x896 points
- 1242x2688 @3x = 414x896 points (same points as XR but different ratio)
- 1170x2532 @3x = 390x844 points
- 1179x2556 @3x = 393x852 points
- 1290x2796 @3x = 430x932 points
- 1206x2622 @3x = 402x874 points
- 1320x2868 @3x = 440x956 points
- 1080x2340 @3x = 360x780 points

- [ ] **Step 4: Verify build**

```bash
cd web && pnpm build
```

Expected: Build succeeds. `dist/index.html` contains all splash screen link tags.

---

## Task 5: Add SKIP_WAITING handler to service worker

**Files:**
- Modify: `web/src/sw.ts`

- [ ] **Step 1: Add message event listener**

Add at the end of `web/src/sw.ts` (after the `notificationclick` handler):

```ts
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
```

This allows the `virtual:pwa-register` `updateSW()` function to trigger activation of the waiting service worker.

---

## Task 6: Add TypeScript declarations for virtual:pwa-register

**Files:**
- Modify: `web/tsconfig.app.json`

The existing `types` array in `tsconfig.app.json` already registers `vite/client` — this is the canonical place for type declarations in this project (the triple-slash reference in `vite-env.d.ts` is redundant with it). Add `vite-plugin-pwa/client` to the same array for consistency.

- [ ] **Step 1: Add `vite-plugin-pwa/client` to the types array**

In `web/tsconfig.app.json`, change line 8:
```json
    "types": ["vite/client"],
```
to:
```json
    "types": ["vite/client", "vite-plugin-pwa/client"],
```

This declares the `virtual:pwa-register` module which exports `registerSW`. The type definitions ship with `vite-plugin-pwa` already in devDependencies.

- [ ] **Step 2: Verify TypeScript is happy**

```bash
cd web && npx tsc --noEmit
```

Expected: No type errors related to `virtual:pwa-register`.

---

## Task 7: Create useServiceWorker hook

**Files:**
- Create: `web/src/shared/hooks/useServiceWorker.ts`

- [ ] **Step 1: Create the hook**

```ts
import { useState, useEffect, useCallback, useRef } from "react";
import { registerSW } from "virtual:pwa-register";

export function useServiceWorker() {
  const [updateAvailable, setUpdateAvailable] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const updateSWRef = useRef<((reloadPage?: boolean) => Promise<void>) | null>(null);
  const registered = useRef(false);

  useEffect(() => {
    if (registered.current) return;
    registered.current = true;

    const updateSW = registerSW({
      onNeedRefresh() {
        setUpdateAvailable(true);
      },
    });
    updateSWRef.current = updateSW;
  }, []);

  const applyUpdate = useCallback(() => {
    updateSWRef.current?.(true);
  }, []);

  const dismiss = useCallback(() => {
    setDismissed(true);
  }, []);

  return {
    showUpdateModal: updateAvailable && !dismissed,
    applyUpdate,
    dismiss,
  };
}
```

Key design decisions:
- `registerSW` from `virtual:pwa-register` is the plugin's API. With `registerType: "prompt"`, it calls `onNeedRefresh` when a new SW is waiting.
- `updateSW(true)` tells the plugin to post `SKIP_WAITING` to the waiting SW and reload the page.
- `dismissed` is local state -- it resets on next app launch (fresh page load), which re-runs the hook and detects the still-waiting SW.
- `registered` ref guard prevents double registration in StrictMode dev mode.

---

## Task 8: Create UpdateModal component

**Files:**
- Create: `web/src/shared/components/UpdateModal.tsx`

Uses native `<dialog>` with `showModal()` to match the existing modal pattern in `OrderDialog` and `IndicatorSheet`. The `<dialog>` top layer eliminates manual z-index management.

- [ ] **Step 1: Create the modal component**

```tsx
import { useRef, useEffect } from "react";

interface UpdateModalProps {
  onUpdate: () => void;
  onDismiss: () => void;
}

export function UpdateModal({ onUpdate, onDismiss }: UpdateModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    ref.current?.showModal();
  }, []);

  return (
    <dialog
      ref={ref}
      onClose={onDismiss}
      onClick={(e) => {
        if (e.target === ref.current) onDismiss();
      }}
      className="w-full max-w-sm rounded-2xl p-6 bg-card border border-white/[0.06] text-white"
    >
      <h2 className="text-foreground text-lg font-semibold mb-2">
        Update Available
      </h2>
      <p className="text-muted text-sm mb-6">
        A new version of Krypton is ready.
      </p>
      <div className="flex gap-3">
        <button
          onClick={onDismiss}
          className="flex-1 py-2.5 rounded-xl text-sm font-medium text-muted bg-surface border border-white/[0.06] active:scale-[0.97] transition-transform"
        >
          Later
        </button>
        <button
          onClick={onUpdate}
          className="flex-1 py-2.5 rounded-xl text-sm font-medium text-surface bg-accent active:scale-[0.97] transition-transform"
        >
          Update Now
        </button>
      </div>
    </dialog>
  );
}
```

Design notes:
- Uses native `<dialog>` with `showModal()` — matches `OrderDialog` and `IndicatorSheet` patterns
- Backdrop click to dismiss via `onClick` target check (same pattern as `OrderDialog`)
- `onClose` event fires on backdrop click and Escape key, both route to `onDismiss`
- No manual z-index — `showModal()` places the dialog in the browser's top layer
- Uses existing Tailwind tokens: `bg-card`, `text-foreground`, `text-muted`, `bg-surface`, `bg-accent`, `border-white/[0.06]`
- `active:scale-[0.97]` for tactile press feedback matching the app's mobile-first feel

---

## Task 9: Test useServiceWorker hook

**Files:**
- Create: `web/src/shared/hooks/useServiceWorker.test.ts`

- [ ] **Step 1: Create the test file**

Mock `virtual:pwa-register` and test the hook's state transitions. Follows the existing test pattern (co-located `.test.ts`, vitest globals, `vi.mock`).

```ts
import { renderHook, act } from "@testing-library/react";
import { useServiceWorker } from "./useServiceWorker";

let onNeedRefreshCb: (() => void) | undefined;
const mockUpdateSW = vi.fn(() => Promise.resolve());

vi.mock("virtual:pwa-register", () => ({
  registerSW: (opts: { onNeedRefresh?: () => void }) => {
    onNeedRefreshCb = opts.onNeedRefresh;
    return mockUpdateSW;
  },
}));

beforeEach(() => {
  onNeedRefreshCb = undefined;
  mockUpdateSW.mockClear();
});

it("starts with modal hidden", () => {
  const { result } = renderHook(() => useServiceWorker());
  expect(result.current.showUpdateModal).toBe(false);
});

it("shows modal when onNeedRefresh fires", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  expect(result.current.showUpdateModal).toBe(true);
});

it("hides modal after dismiss", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  act(() => result.current.dismiss());
  expect(result.current.showUpdateModal).toBe(false);
});

it("calls updateSW(true) on applyUpdate", () => {
  const { result } = renderHook(() => useServiceWorker());
  act(() => onNeedRefreshCb?.());
  act(() => result.current.applyUpdate());
  expect(mockUpdateSW).toHaveBeenCalledWith(true);
});
```

- [ ] **Step 2: Run the test**

```bash
cd web && npx vitest run src/shared/hooks/useServiceWorker.test.ts
```

Expected: All 4 tests pass.

---

## Task 10: Wire into App.tsx

**Files:**
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Add imports**

Add after existing imports (line 13):

```ts
import { useServiceWorker } from "./shared/hooks/useServiceWorker";
import { UpdateModal } from "./shared/components/UpdateModal";
```

- [ ] **Step 2: Use the hook and render the modal**

Inside the `App` component, after the existing `useLivePrice` call (line 23), add:

```ts
  const { showUpdateModal, applyUpdate, dismiss } = useServiceWorker();
```

Inside the JSX return, add before `<Layout>` (after `<AlertToast />`):

```tsx
      {showUpdateModal && <UpdateModal onUpdate={applyUpdate} onDismiss={dismiss} />}
```

- [ ] **Step 3: Verify build**

```bash
cd web && pnpm build
```

Expected: Build succeeds with no type errors.

---

## Task 11: Final verification

- [ ] **Step 1: Run full build and check outputs**

```bash
cd web && pnpm build
```

Verify:
- `dist/manifest.webmanifest` contains `icon-512-maskable.png` with `"purpose": "maskable"`
- `dist/manifest.webmanifest` has `theme_color` and `background_color` set to `#0B0E11`
- `dist/index.html` contains all 11 `apple-touch-startup-image` link tags
- `dist/index.html` has `apple-touch-icon` pointing to `apple-touch-icon-180.png`
- `dist/sw.js` contains the `SKIP_WAITING` message handler
- Splash screen PNGs are in `dist/` but NOT in the precache manifest inside `sw.js`

- [ ] **Step 2: Run linter**

```bash
cd web && pnpm lint
```

Expected: No lint errors.

- [ ] **Step 3: Commit**

```bash
git add web/public/apple-touch-icon-180.png web/public/icon-512-maskable.png web/public/apple-splash-*.png web/index.html web/vite.config.ts web/src/sw.ts web/tsconfig.app.json web/src/shared/hooks/useServiceWorker.ts web/src/shared/hooks/useServiceWorker.test.ts web/src/shared/components/UpdateModal.tsx web/src/App.tsx
git commit -m "feat(pwa): iOS splash screens, maskable icon, and app update modal"
```
