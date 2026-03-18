# Vite PWA Improvements Design

## Overview

Enhance the existing Vite PWA setup to provide a polished iOS install experience and a user-facing app update modal. The app is primarily used on iOS.

## Goals

1. **iOS install experience** -- proper apple-touch-icon, splash screens for all common iOS device sizes, maskable icon for Android
2. **App update UX** -- modal dialog when a new service worker is detected, with "Update Now" and "Later" options

## Non-Goals

- Offline/runtime caching of API responses
- Custom in-app install prompt (rely on browser default)
- Background sync
- Landscape splash screens
- iPad splash screens (mobile-first, iPhone only)

## Current State

- `vite-plugin-pwa` v1.2.0 with `injectManifest` strategy
- Custom service worker (`sw.ts`) handles precaching + push notifications
- Basic manifest: name, theme_color, standalone display, 192/512 icons
- `index.html` has `apple-mobile-web-app-capable` and `apple-mobile-web-app-status-bar-style`
- Basic `apple-touch-icon` pointing to `/icon-192.png`
- No SW update detection or update UI
- No splash screen images

## Approach

Enhance the existing `injectManifest` setup. No strategy change needed -- the current custom SW with push handlers stays intact.

---

## Section 1: iOS Install Experience

### Icons

Generate and add to `web/public/`:

| File | Size | Purpose |
|------|------|---------|
| `apple-touch-icon-180.png` | 180x180 | iOS standard touch icon |
| `icon-512-maskable.png` | 512x512 | Android maskable icon (with safe zone padding) |

Keep existing `icon-192.png` and `icon-512.png`.

### Splash Screens

Generate `apple-splash-{width}x{height}@{scale}x.png` images for the following iOS device sizes:

| Device | Portrait | Scale |
|--------|----------|-------|
| iPhone SE (3rd gen) | 750x1334 | 2x |
| iPhone 8 Plus | 1242x2208 | 3x |
| iPhone X / XS / 11 Pro | 1125x2436 | 3x |
| iPhone XR / 11 | 828x1792 | 2x |
| iPhone XS Max / 11 Pro Max | 1242x2688 | 3x |
| iPhone 12 / 13 / 14 | 1170x2532 | 3x |
| iPhone 14 Pro / 15 / 15 Pro | 1179x2556 | 3x |
| iPhone 14 Pro Max / 15 Plus / 15 Pro Max | 1290x2796 | 3x |
| iPhone 16 Pro | 1206x2622 | 3x |
| iPhone 16 Pro Max | 1320x2868 | 3x |

| iPhone 12 mini / 13 mini | 1080x2340 | 3x |

Each splash screen: dark background (`#0B0E11`, matching `theme.colors.surface`), centered Krypton app icon.

### `index.html` Changes

```html
<!-- Update theme-color to match surface -->
<meta name="theme-color" content="#0B0E11" />

<!-- Replace existing apple-touch-icon -->
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon-180.png" />

<!-- Add splash screens with media queries -->
<link rel="apple-touch-startup-image"
  href="/apple-splash-750x1334.png"
  media="(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)" />
<!-- ... one link tag per device size ... -->
```

### `vite.config.ts` Changes

Three changes:

1. **Change `registerType` from `"autoUpdate"` to `"prompt"`**. The current `autoUpdate` setting auto-activates new service workers immediately, which conflicts with the update modal flow. Changing to `"prompt"` makes the plugin wait for explicit activation.

2. **Update `theme_color` and `background_color`** from `"#121212"` to `"#0B0E11"` to match `theme.colors.surface` and the splash screen backgrounds.

3. **Add maskable icon** to the manifest icons array.

4. **Exclude splash screens from precaching** by updating `globPatterns` to not match `apple-splash-*.png`. Splash screens are fetched by the OS during "Add to Home Screen" launch, not by the service worker -- precaching them would add ~3-5MB of unnecessary download.

```ts
registerType: "prompt",
manifest: {
  // ...
  theme_color: "#0B0E11",
  background_color: "#0B0E11",
  icons: [
    { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
    { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
    { src: "/icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
  ],
},
injectManifest: {
  globPatterns: ["**/*.{js,css,html,ico,svg}", "icon-*.png", "apple-touch-icon-*.png"],
},
```

---

## Section 2: App Update UX

### Service Worker Changes (`sw.ts`)

Add a message listener for skip-waiting:

```ts
self.addEventListener("message", (event) => {
  if (event.data?.type === "SKIP_WAITING") {
    self.skipWaiting();
  }
});
```

### `useServiceWorker` Hook (`shared/hooks/useServiceWorker.ts`)

Responsibilities:
- Use the plugin's `registerSW` from `virtual:pwa-register` (not raw `navigator.serviceWorker.register()`) to avoid double registration
- Detect when a new SW is installed (update available)
- Expose `updateAvailable: boolean` and `applyUpdate: () => void`

Logic:
1. On mount, call `registerSW({ onNeedRefresh() })` from `virtual:pwa-register`. With `registerType: "prompt"`, the plugin calls `onNeedRefresh` when a new SW is waiting to activate.
2. `onNeedRefresh` sets `updateAvailable = true`
3. `applyUpdate()` calls the `updateSW()` function returned by `registerSW()`, which handles skip-waiting and reload internally

"Later" behavior: dismissing the modal sets local component state to hide it. The waiting SW persists, so on next app launch (fresh page load), `registerSW` fires `onNeedRefresh` again and the modal reappears.

Note: a `virtual:pwa-register` type declaration file (`vite-env-pwa.d.ts`) will be needed for TypeScript.

### `UpdateModal` Component (`shared/components/UpdateModal.tsx`)

A centered modal overlay consistent with the existing dark theme (`bg-card`, `text-foreground`, `border-white/[0.06]`):

- Backdrop: semi-transparent black overlay
- Title: "Update Available"
- Body: "A new version of Krypton is ready."
- "Update Now" button: accent color, calls `applyUpdate()`
- "Later" button: muted style, dismisses modal

### Wiring (`App.tsx`)

Import `useServiceWorker` and `UpdateModal`. Render the modal at the top level, outside `Layout`, so it overlays everything including the nav bar.

---

## Files Changed

| File | Change |
|------|--------|
| `web/public/apple-touch-icon-180.png` | New -- 180x180 iOS icon |
| `web/public/icon-512-maskable.png` | New -- maskable icon |
| `web/public/apple-splash-*.png` | New -- 11 splash screen images (portrait only, iPhone) |
| `web/index.html` | Update theme-color, apple-touch-icon, add splash screen link tags |
| `web/vite.config.ts` | Change registerType to "prompt", update theme/bg colors, add maskable icon, narrow globPatterns |
| `web/src/sw.ts` | Add SKIP_WAITING message handler |
| `web/src/shared/hooks/useServiceWorker.ts` | New -- SW registration + update detection hook |
| `web/src/shared/components/UpdateModal.tsx` | New -- update modal component |
| `web/src/App.tsx` | Wire in useServiceWorker + UpdateModal |
| `web/tsconfig.app.json` | Modify -- add `vite-plugin-pwa/client` to `types` array for `virtual:pwa-register` declarations |

## Testing

- Verify `pnpm build` produces correct manifest.webmanifest with maskable icon
- Verify splash screen meta tags render in index.html
- Manual test on iOS: add to home screen, verify splash screen appears on launch
- Manual test update flow: build v1, install SW, build v2, verify modal appears on reload
