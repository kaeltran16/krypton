# Krypton PWA Migration Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the React Native mobile app with a lightweight PWA built on React + Vite + Tailwind, keeping push notifications and real-time WebSocket signals.

**Architecture:** Client-side SPA served as a PWA with service worker for offline caching and push notifications. Connects to the existing FastAPI backend via WebSocket for real-time signals and REST for history. No SSR needed — single-user personal tool. State-based tab switching (2 views: feed + settings), no router library.

**Tech Stack:** React 19, Vite, TypeScript, Tailwind CSS 3, Zustand 5, vite-plugin-pwa (Workbox), Vitest

---

### Task 1: Scaffold Web Project

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/tsconfig.json`
- Create: `web/tsconfig.app.json`
- Create: `web/tsconfig.node.json`
- Create: `web/tailwind.config.ts`
- Create: `web/postcss.config.js`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/index.css`
- Create: `web/src/vite-env.d.ts`

**Step 1: Create Vite project**

```bash
cd C:/Users/kael02/IdeaProjects/krypton
npm create vite@latest web -- --template react-ts
```

Expected: `web/` directory created with React + TypeScript template.

**Step 2: Install dependencies**

```bash
cd web
npm install zustand
npm install -D tailwindcss@3 postcss autoprefixer vite-plugin-pwa vitest @testing-library/react @testing-library/jest-dom jsdom
npx tailwindcss init -p --ts
```

Expected: All packages installed, `tailwind.config.ts` and `postcss.config.js` created.

**Step 3: Configure Tailwind**

Replace `web/tailwind.config.ts`:

```typescript
import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#121212",
        card: "#1A1A1A",
        long: "#22C55E",
        short: "#EF4444",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
    },
  },
  safelist: [
    "text-long", "text-short",
    "bg-long/5", "bg-short/5",
    "bg-long/10", "bg-short/10",
    "bg-long/20",
    "border-long/30", "border-short/30",
  ],
  plugins: [],
} satisfies Config;
```

**Step 4: Configure Vite with PWA and Vitest**

Replace `web/vite.config.ts`:

```typescript
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Krypton",
        short_name: "Krypton",
        description: "AI-enhanced crypto signal copilot",
        theme_color: "#121212",
        background_color: "#121212",
        display: "standalone",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      workbox: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
      },
    }),
  ],
  test: {
    globals: true,
    environment: "jsdom",
  },
});
```

**Step 5: Set up global CSS**

Replace `web/src/index.css`:

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

body {
  background-color: #121212;
  color: #ffffff;
  font-family: system-ui, -apple-system, sans-serif;
  margin: 0;
  -webkit-font-smoothing: antialiased;
}

dialog::backdrop {
  background: rgba(0, 0, 0, 0.6);
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
  background: #1a1a1a;
  color: #ffffff;
}
```

**Step 6: Create placeholder App**

Replace `web/src/App.tsx`:

```tsx
export default function App() {
  return <div className="min-h-screen bg-surface text-white p-4">Krypton</div>;
}
```

Replace `web/src/main.tsx`:

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

Create `web/.env.example`:

```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_API_KEY=
VITE_VAPID_PUBLIC_KEY=
```

Copy to `web/.env` for local development and fill in values.

**Step 7: Verify build**

```bash
cd web && npm run build
```

Expected: Build succeeds, `dist/` created with bundled assets.

**Step 8: Verify dev server**

```bash
cd web && npm run dev
```

Expected: Dev server starts at `http://localhost:5173`, shows "Krypton" text on dark background.

**Step 9: Commit**

```bash
git add web/ web/.env.example
git commit -m "feat(web): scaffold PWA with Vite, React, Tailwind, and PWA plugin"
```

---

### Task 2: Shared Types, Constants, and Format Utilities

**Files:**
- Create: `web/src/features/signals/types.ts`
- Create: `web/src/features/settings/types.ts`
- Create: `web/src/shared/lib/constants.ts`
- Create: `web/src/shared/lib/format.ts`
- Create: `web/src/shared/lib/format.test.ts`

**Step 1: Create signal types**

These match the backend `SignalResult` model and the DB `Signal` columns.

`web/src/features/signals/types.ts`:

```typescript
export type Direction = "LONG" | "SHORT";
export type Confidence = "HIGH" | "MEDIUM" | "LOW";
export type LlmOpinion = "confirm" | "caution" | "contradict";
export type Timeframe = "15m" | "1h" | "4h";

export interface SignalLevels {
  entry: number;
  stop_loss: number;
  take_profit_1: number;
  take_profit_2: number;
}

export interface Signal {
  id: number;
  pair: string;
  timeframe: Timeframe;
  direction: Direction;
  final_score: number;
  confidence: Confidence;
  traditional_score: number;
  llm_opinion: LlmOpinion | null;
  explanation: string | null;
  levels: SignalLevels;
  created_at: string;
}
```

Note: `id` is `number` (matches DB integer PK). `confidence` is derived from `llm_confidence` on the backend — the REST endpoint will map it. `created_at` instead of `timestamp` to match the DB column name.

**Step 2: Create settings types**

`web/src/features/settings/types.ts`:

```typescript
import type { Timeframe } from "../signals/types";

export interface Settings {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
}

export const DEFAULT_SETTINGS: Settings = {
  pairs: ["BTC-USDT-SWAP", "ETH-USDT-SWAP"],
  threshold: 50,
  timeframes: ["15m", "1h", "4h"],
  notificationsEnabled: true,
  apiBaseUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
};
```

**Step 3: Create constants**

`web/src/shared/lib/constants.ts`:

```typescript
export const API_BASE_URL =
  import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export const WS_BASE_URL =
  import.meta.env.VITE_WS_URL ?? "ws://localhost:8000";

export const API_KEY = import.meta.env.VITE_API_KEY ?? "";

export const VAPID_PUBLIC_KEY = import.meta.env.VITE_VAPID_PUBLIC_KEY ?? "";

export const AVAILABLE_PAIRS = [
  "BTC-USDT-SWAP",
  "ETH-USDT-SWAP",
] as const;
```

**Step 4: Write failing format tests**

`web/src/shared/lib/format.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { formatPrice, formatScore, formatTime } from "./format";

describe("formatPrice", () => {
  it("formats BTC-range prices with 2 decimals", () => {
    expect(formatPrice(85432.15)).toBe("85,432.15");
  });

  it("formats small prices with more precision", () => {
    expect(formatPrice(0.00045)).toBe("0.00045");
  });

  it("formats zero", () => {
    expect(formatPrice(0)).toBe("0.00");
  });
});

describe("formatScore", () => {
  it("formats positive scores with + prefix", () => {
    expect(formatScore(72)).toBe("+72");
  });

  it("formats negative scores with - prefix", () => {
    expect(formatScore(-45)).toBe("-45");
  });

  it("formats zero without prefix", () => {
    expect(formatScore(0)).toBe("0");
  });
});

describe("formatTime", () => {
  it("formats ISO timestamp to HH:MM", () => {
    expect(formatTime("2026-02-27T14:35:00Z")).toMatch(/\d{2}:\d{2}/);
  });
});
```

**Step 5: Run tests to verify they fail**

```bash
cd web && npx vitest run src/shared/lib/format.test.ts
```

Expected: FAIL — `format` module does not exist yet.

**Step 6: Implement format utilities**

`web/src/shared/lib/format.ts`:

```typescript
const priceFormatter = new Intl.NumberFormat("en-US", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const smallPriceFormatter = new Intl.NumberFormat("en-US", {
  minimumSignificantDigits: 3,
  maximumSignificantDigits: 5,
});

export function formatPrice(price: number): string {
  if (price === 0) return "0.00";
  if (Math.abs(price) < 1) return smallPriceFormatter.format(price);
  return priceFormatter.format(price);
}

export function formatScore(score: number): string {
  if (score > 0) return `+${score}`;
  return String(score);
}

export function formatTime(iso: string): string {
  const d = new Date(iso);
  const h = String(d.getHours()).padStart(2, "0");
  const m = String(d.getMinutes()).padStart(2, "0");
  return `${h}:${m}`;
}
```

**Step 7: Run tests to verify they pass**

```bash
cd web && npx vitest run src/shared/lib/format.test.ts
```

Expected: All 6 tests PASS.

**Step 8: Commit**

```bash
git add web/src/features/ web/src/shared/
git commit -m "feat(web): add types, constants, and format utilities with tests"
```

---

### Task 3: WebSocket Client

**Files:**
- Create: `web/src/shared/lib/websocket.ts`
- Create: `web/src/shared/lib/websocket.test.ts`

**Step 1: Write failing WebSocket tests**

`web/src/shared/lib/websocket.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { WebSocketManager } from "./websocket";

let mockInstances: any[];

beforeEach(() => {
  mockInstances = [];
  vi.useFakeTimers();

  vi.stubGlobal(
    "WebSocket",
    class MockWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSING = 2;
      static CLOSED = 3;

      readyState = 0;
      onopen: (() => void) | null = null;
      onclose: (() => void) | null = null;
      onmessage: ((e: any) => void) | null = null;
      onerror: (() => void) | null = null;
      url: string;
      send = vi.fn();
      close = vi.fn();

      constructor(url: string) {
        this.url = url;
        mockInstances.push(this);
      }
    },
  );
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("WebSocketManager", () => {
  it("connects and fires onConnected", () => {
    const ws = new WebSocketManager("ws://test");
    const onConnected = vi.fn();
    ws.onConnected = onConnected;
    ws.connect();

    mockInstances[0].readyState = 1;
    mockInstances[0].onopen!();

    expect(onConnected).toHaveBeenCalledOnce();
  });

  it("parses JSON messages and fires onMessage", () => {
    const ws = new WebSocketManager("ws://test");
    const onMessage = vi.fn();
    ws.onMessage = onMessage;
    ws.connect();

    const data = { type: "signal", pair: "BTC" };
    mockInstances[0].onmessage!({ data: JSON.stringify(data) });

    expect(onMessage).toHaveBeenCalledWith(data);
  });

  it("ignores malformed messages", () => {
    const ws = new WebSocketManager("ws://test");
    const onMessage = vi.fn();
    ws.onMessage = onMessage;
    ws.connect();

    mockInstances[0].onmessage!({ data: "not-json{" });

    expect(onMessage).not.toHaveBeenCalled();
  });

  it("reconnects with exponential backoff after close", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();
    expect(mockInstances).toHaveLength(1);

    mockInstances[0].onclose!();
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(2);

    mockInstances[1].onclose!();
    vi.advanceTimersByTime(2000);
    expect(mockInstances).toHaveLength(3);
  });

  it("does not reconnect after disconnect()", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    ws.disconnect();
    mockInstances[0].onclose?.();
    vi.advanceTimersByTime(5000);

    expect(mockInstances).toHaveLength(1);
  });

  it("resets backoff delay after successful connection", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    mockInstances[0].onclose!();
    vi.advanceTimersByTime(1000);
    mockInstances[1].readyState = 1;
    mockInstances[1].onopen!();

    mockInstances[1].onclose!();
    vi.advanceTimersByTime(1000);
    expect(mockInstances).toHaveLength(3);
  });

  it("sends data when connected", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();
    mockInstances[0].readyState = 1;

    ws.send('{"type":"subscribe"}');

    expect(mockInstances[0].send).toHaveBeenCalledWith('{"type":"subscribe"}');
  });

  it("silently drops send when not connected", () => {
    const ws = new WebSocketManager("ws://test");
    ws.connect();

    ws.send('{"type":"subscribe"}');

    expect(mockInstances[0].send).not.toHaveBeenCalled();
  });
});
```

**Step 2: Run tests to verify they fail**

```bash
cd web && npx vitest run src/shared/lib/websocket.test.ts
```

Expected: FAIL — `websocket` module does not exist.

**Step 3: Implement WebSocket client**

`web/src/shared/lib/websocket.ts`:

```typescript
export class WebSocketManager {
  private ws: WebSocket | null = null;
  private reconnectDelay = 1000;
  private maxReconnectDelay = 30000;
  private shouldReconnect = true;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  onMessage: ((data: unknown) => void) | null = null;
  onConnected: (() => void) | null = null;
  onDisconnected: (() => void) | null = null;

  constructor(private url: string) {}

  connect() {
    this.shouldReconnect = true;
    this.createConnection();
  }

  disconnect() {
    this.shouldReconnect = false;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  send(data: string) {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(data);
    }
  }

  private createConnection() {
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      this.reconnectDelay = 1000;
      this.onConnected?.();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this.onMessage?.(data);
      } catch {
        // ignore malformed messages
      }
    };

    this.ws.onclose = () => {
      this.onDisconnected?.();
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      this.ws?.close();
    };
  }

  private scheduleReconnect() {
    if (!this.shouldReconnect) return;
    this.reconnectTimer = setTimeout(() => {
      this.createConnection();
      this.reconnectDelay = Math.min(
        this.reconnectDelay * 2,
        this.maxReconnectDelay,
      );
    }, this.reconnectDelay);
  }
}
```

**Step 4: Run tests to verify they pass**

```bash
cd web && npx vitest run src/shared/lib/websocket.test.ts
```

Expected: All 7 tests PASS.

**Step 5: Commit**

```bash
git add web/src/shared/lib/websocket.ts web/src/shared/lib/websocket.test.ts
git commit -m "feat(web): add WebSocket client with reconnect and tests"
```

---

### Task 4: Zustand Stores

**Files:**
- Create: `web/src/features/signals/store.ts`
- Create: `web/src/features/signals/store.test.ts`
- Create: `web/src/features/settings/store.ts`
- Create: `web/src/features/settings/store.test.ts`

**Step 1: Write failing signal store tests**

`web/src/features/signals/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useSignalStore } from "./store";
import type { Signal } from "./types";

function createSignal(overrides: Partial<Signal> = {}): Signal {
  return {
    id: 1,
    pair: "BTC-USDT-SWAP",
    timeframe: "1h",
    direction: "LONG",
    final_score: 75,
    confidence: "HIGH",
    traditional_score: 70,
    llm_opinion: "confirm",
    explanation: "Strong trend",
    levels: { entry: 85000, stop_loss: 84000, take_profit_1: 87000, take_profit_2: 89000 },
    created_at: "2026-02-27T12:00:00Z",
    ...overrides,
  };
}

describe("useSignalStore", () => {
  beforeEach(() => {
    useSignalStore.getState().clear();
  });

  it("starts empty", () => {
    const state = useSignalStore.getState();
    expect(state.signals).toEqual([]);
    expect(state.selectedSignal).toBeNull();
    expect(state.connected).toBe(false);
  });

  it("adds signal to front of list", () => {
    const s1 = createSignal({ id: 1 });
    const s2 = createSignal({ id: 2 });
    useSignalStore.getState().addSignal(s1);
    useSignalStore.getState().addSignal(s2);
    expect(useSignalStore.getState().signals[0].id).toBe(2);
    expect(useSignalStore.getState().signals[1].id).toBe(1);
  });

  it("caps signals at 100", () => {
    for (let i = 0; i < 110; i++) {
      useSignalStore.getState().addSignal(createSignal({ id: i }));
    }
    expect(useSignalStore.getState().signals).toHaveLength(100);
  });

  it("selects and clears signal", () => {
    const s = createSignal();
    useSignalStore.getState().selectSignal(s);
    expect(useSignalStore.getState().selectedSignal).toEqual(s);

    useSignalStore.getState().clearSelection();
    expect(useSignalStore.getState().selectedSignal).toBeNull();
  });

  it("tracks connection status", () => {
    useSignalStore.getState().setConnected(true);
    expect(useSignalStore.getState().connected).toBe(true);
  });
});
```

**Step 2: Write failing settings store tests**

`web/src/features/settings/store.test.ts`:

```typescript
import { describe, it, expect, beforeEach } from "vitest";
import { useSettingsStore } from "./store";

describe("useSettingsStore", () => {
  beforeEach(() => {
    useSettingsStore.getState().reset();
    localStorage.clear();
  });

  it("starts with defaults", () => {
    const state = useSettingsStore.getState();
    expect(state.pairs).toEqual(["BTC-USDT-SWAP", "ETH-USDT-SWAP"]);
    expect(state.threshold).toBe(50);
    expect(state.timeframes).toEqual(["15m", "1h", "4h"]);
    expect(state.notificationsEnabled).toBe(true);
  });

  it("updates pairs", () => {
    useSettingsStore.getState().setPairs(["BTC-USDT-SWAP"]);
    expect(useSettingsStore.getState().pairs).toEqual(["BTC-USDT-SWAP"]);
  });

  it("updates threshold", () => {
    useSettingsStore.getState().setThreshold(75);
    expect(useSettingsStore.getState().threshold).toBe(75);
  });

  it("updates timeframes", () => {
    useSettingsStore.getState().setTimeframes(["4h"]);
    expect(useSettingsStore.getState().timeframes).toEqual(["4h"]);
  });

  it("resets to defaults", () => {
    useSettingsStore.getState().setThreshold(90);
    useSettingsStore.getState().reset();
    expect(useSettingsStore.getState().threshold).toBe(50);
  });
});
```

**Step 3: Run tests to verify they fail**

```bash
cd web && npx vitest run src/features/
```

Expected: FAIL — store modules do not exist.

**Step 4: Implement signal store**

`web/src/features/signals/store.ts`:

```typescript
import { create } from "zustand";
import type { Signal } from "./types";

const MAX_SIGNALS = 100;

interface SignalState {
  signals: Signal[];
  selectedSignal: Signal | null;
  connected: boolean;
  addSignal: (signal: Signal) => void;
  setSignals: (signals: Signal[]) => void;
  selectSignal: (signal: Signal) => void;
  clearSelection: () => void;
  setConnected: (connected: boolean) => void;
  clear: () => void;
}

export const useSignalStore = create<SignalState>((set) => ({
  signals: [],
  selectedSignal: null,
  connected: false,
  addSignal: (signal) =>
    set((state) => ({
      signals: [signal, ...state.signals].slice(0, MAX_SIGNALS),
    })),
  setSignals: (signals) => set({ signals: signals.slice(0, MAX_SIGNALS) }),
  selectSignal: (signal) => set({ selectedSignal: signal }),
  clearSelection: () => set({ selectedSignal: null }),
  setConnected: (connected) => set({ connected }),
  clear: () => set({ signals: [], selectedSignal: null, connected: false }),
}));
```

**Step 5: Implement settings store**

`web/src/features/settings/store.ts`:

```typescript
import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { Timeframe } from "../signals/types";
import { DEFAULT_SETTINGS } from "./types";

interface SettingsState {
  pairs: string[];
  threshold: number;
  timeframes: Timeframe[];
  notificationsEnabled: boolean;
  apiBaseUrl: string;
  setPairs: (pairs: string[]) => void;
  setThreshold: (threshold: number) => void;
  setTimeframes: (timeframes: Timeframe[]) => void;
  setNotificationsEnabled: (enabled: boolean) => void;
  setApiBaseUrl: (url: string) => void;
  reset: () => void;
}

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      ...DEFAULT_SETTINGS,
      setPairs: (pairs) => set({ pairs }),
      setThreshold: (threshold) => set({ threshold }),
      setTimeframes: (timeframes) => set({ timeframes }),
      setNotificationsEnabled: (enabled) =>
        set({ notificationsEnabled: enabled }),
      setApiBaseUrl: (url) => set({ apiBaseUrl: url }),
      reset: () => set(DEFAULT_SETTINGS),
    }),
    {
      name: "krypton-settings",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({
        pairs: state.pairs,
        threshold: state.threshold,
        timeframes: state.timeframes,
        notificationsEnabled: state.notificationsEnabled,
        apiBaseUrl: state.apiBaseUrl,
      }),
    },
  ),
);
```

**Step 6: Run tests to verify they pass**

```bash
cd web && npx vitest run src/features/
```

Expected: All 10 tests PASS.

**Step 7: Commit**

```bash
git add web/src/features/
git commit -m "feat(web): add signal and settings Zustand stores with tests"
```

---

### Task 5: API Client

**Files:**
- Create: `web/src/shared/lib/api.ts`

No unit tests — thin wrapper over `fetch`. Tested via integration when the full app runs against the backend.

**Step 1: Implement API client**

`web/src/shared/lib/api.ts`:

```typescript
import { API_BASE_URL, API_KEY } from "./constants";
import type { Signal } from "../../features/signals/types";

const headers: HeadersInit = {
  "Content-Type": "application/json",
  ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, { headers, ...init });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText}`);
  }
  return res.json();
}

export const api = {
  getSignals: (params?: {
    pair?: string;
    timeframe?: string;
    limit?: number;
  }) => {
    const query = new URLSearchParams();
    if (params?.pair) query.set("pair", params.pair);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.limit) query.set("limit", String(params.limit));
    const qs = query.toString();
    return request<Signal[]>(`/api/signals${qs ? `?${qs}` : ""}`);
  },
};
```

**Step 2: Commit**

```bash
git add web/src/shared/lib/api.ts
git commit -m "feat(web): add API client"
```

---

### Task 6: App Shell and Layout

**Files:**
- Modify: `web/src/App.tsx`
- Create: `web/src/shared/components/Layout.tsx`
- Modify: `web/index.html`

**Step 1: Update index.html for dark theme**

Update the `<head>` in `web/index.html` to include:

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <meta name="theme-color" content="#121212" />
    <meta name="apple-mobile-web-app-capable" content="yes" />
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
    <title>Krypton</title>
    <link rel="icon" type="image/png" href="/icon-192.png" />
    <link rel="apple-touch-icon" href="/icon-192.png" />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

**Step 2: Create Layout component**

`web/src/shared/components/Layout.tsx`:

```tsx
import { useState, type ReactNode } from "react";

type Tab = "feed" | "settings";

export function Layout({
  feed,
  settings,
}: {
  feed: ReactNode;
  settings: ReactNode;
}) {
  const [tab, setTab] = useState<Tab>("feed");

  return (
    <div className="min-h-screen bg-surface text-white flex flex-col">
      <main className="flex-1 overflow-y-auto pb-16">{tab === "feed" ? feed : settings}</main>
      <nav className="fixed bottom-0 left-0 right-0 bg-card border-t border-gray-800 flex safe-bottom">
        <TabButton active={tab === "feed"} onClick={() => setTab("feed")} label="Signals" />
        <TabButton active={tab === "settings"} onClick={() => setTab("settings")} label="Settings" />
      </nav>
    </div>
  );
}

function TabButton({
  active,
  onClick,
  label,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
}) {
  return (
    <button
      onClick={onClick}
      className={`flex-1 py-3 text-center text-sm font-medium transition-colors ${
        active ? "text-long" : "text-gray-500"
      }`}
    >
      {label}
    </button>
  );
}
```

**Step 3: Wire up App**

Replace `web/src/App.tsx`:

```tsx
import { Layout } from "./shared/components/Layout";

function FeedPlaceholder() {
  return <div className="p-4 text-gray-400">Signal feed coming soon...</div>;
}

function SettingsPlaceholder() {
  return <div className="p-4 text-gray-400">Settings coming soon...</div>;
}

export default function App() {
  return <Layout feed={<FeedPlaceholder />} settings={<SettingsPlaceholder />} />;
}
```

**Step 4: Verify it renders**

```bash
cd web && npm run dev
```

Expected: Dark background, bottom tab bar with "Signals" and "Settings" tabs, switching works.

**Step 5: Commit**

```bash
git add web/src/App.tsx web/src/shared/components/ web/index.html
git commit -m "feat(web): add app shell with tab-based layout"
```

---

### Task 7: Signal Card Component

**Files:**
- Create: `web/src/features/signals/components/SignalCard.tsx`

**Step 1: Implement SignalCard**

`web/src/features/signals/components/SignalCard.tsx`:

```tsx
import type { Signal } from "../types";
import { formatScore, formatTime } from "../../../shared/lib/format";

export function SignalCard({
  signal,
  onSelect,
}: {
  signal: Signal;
  onSelect: (signal: Signal) => void;
}) {
  const isLong = signal.direction === "LONG";

  return (
    <button
      onClick={() => onSelect(signal)}
      className={`w-full p-4 rounded-lg border text-left transition-colors
        ${isLong ? "border-long/30 bg-long/5 hover:bg-long/10" : "border-short/30 bg-short/5 hover:bg-short/10"}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{signal.pair}</span>
          <span className="text-xs text-gray-400">{signal.timeframe}</span>
        </div>
        <span className={`font-mono font-bold ${isLong ? "text-long" : "text-short"}`}>
          {signal.direction} {formatScore(signal.final_score)}
        </span>
      </div>
      <div className="flex items-center justify-between mt-2">
        <ConfidenceBadge confidence={signal.confidence} />
        <span className="text-xs text-gray-500">
          {formatTime(signal.created_at)}
        </span>
      </div>
    </button>
  );
}

function ConfidenceBadge({ confidence }: { confidence: Signal["confidence"] }) {
  const styles = {
    HIGH: "bg-yellow-500/20 text-yellow-400",
    MEDIUM: "bg-blue-500/20 text-blue-400",
    LOW: "bg-gray-500/20 text-gray-400",
  };

  return (
    <span className={`text-xs px-2 py-0.5 rounded ${styles[confidence]}`}>
      {confidence}
    </span>
  );
}
```

**Step 2: Commit**

```bash
git add web/src/features/signals/components/SignalCard.tsx
git commit -m "feat(web): add SignalCard component"
```

---

### Task 8: Signal Detail Dialog

**Files:**
- Create: `web/src/features/signals/components/SignalDetail.tsx`

**Step 1: Implement SignalDetail dialog**

Uses the native `<dialog>` element styled in `index.css` (Task 1, Step 5).

`web/src/features/signals/components/SignalDetail.tsx`:

```tsx
import { useEffect, useRef } from "react";
import type { Signal } from "../types";
import { formatPrice, formatScore } from "../../../shared/lib/format";

export function SignalDetail({
  signal,
  onClose,
}: {
  signal: Signal | null;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;

    if (signal) {
      dialog.showModal();
    } else {
      dialog.close();
    }
  }, [signal]);

  if (!signal) return null;

  const isLong = signal.direction === "LONG";
  const color = isLong ? "text-long" : "text-short";

  return (
    <dialog ref={ref} onClose={onClose} onClick={(e) => {
      if (e.target === ref.current) onClose();
    }}>
      {/* header */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-lg font-bold">{signal.pair}</span>
            <span className="ml-2 text-sm text-gray-400">{signal.timeframe}</span>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-white text-xl leading-none">&times;</button>
        </div>
        <div className={`text-2xl font-mono font-bold mt-1 ${color}`}>
          {signal.direction} {formatScore(signal.final_score)}
        </div>
      </div>

      {/* score breakdown */}
      <div className="p-4 border-b border-gray-800">
        <h3 className="text-sm text-gray-400 mb-2">Score Breakdown</h3>
        <div className="grid grid-cols-2 gap-2 text-sm">
          <div>
            Traditional: <span className="font-mono">{formatScore(signal.traditional_score)}</span>
          </div>
          <div>
            LLM: <span className="font-mono">{signal.llm_opinion ?? "N/A"}</span>
          </div>
        </div>
      </div>

      {/* AI analysis */}
      {signal.explanation && (
        <div className="p-4 border-b border-gray-800">
          <h3 className="text-sm text-gray-400 mb-2">AI Analysis</h3>
          <p className="text-sm text-gray-300 leading-relaxed">{signal.explanation}</p>
        </div>
      )}

      {/* price levels */}
      <div className="p-4">
        <h3 className="text-sm text-gray-400 mb-2">Price Levels</h3>
        <div className="font-mono text-sm space-y-1">
          <LevelRow label="Entry" value={signal.levels.entry} />
          <LevelRow label="Stop Loss" value={signal.levels.stop_loss} className="text-short" />
          <LevelRow label="TP 1" value={signal.levels.take_profit_1} className="text-long" />
          <LevelRow label="TP 2" value={signal.levels.take_profit_2} className="text-long" />
        </div>
      </div>
    </dialog>
  );
}

function LevelRow({
  label,
  value,
  className = "",
}: {
  label: string;
  value: number;
  className?: string;
}) {
  return (
    <div className="flex justify-between">
      <span className={`text-gray-400 ${className}`}>{label}</span>
      <span>{formatPrice(value)}</span>
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add web/src/features/signals/components/SignalDetail.tsx
git commit -m "feat(web): add SignalDetail dialog component"
```

---

### Task 9: Signal Feed Page with WebSocket Hook

**Files:**
- Create: `web/src/features/signals/hooks/useSignalWebSocket.ts`
- Create: `web/src/features/signals/components/SignalFeed.tsx`
- Create: `web/src/features/signals/components/ConnectionStatus.tsx`

**Step 1: Implement useSignalWebSocket hook**

`web/src/features/signals/hooks/useSignalWebSocket.ts`:

```typescript
import { useEffect, useRef } from "react";
import { WebSocketManager } from "../../../shared/lib/websocket";
import { WS_BASE_URL, API_KEY } from "../../../shared/lib/constants";
import { useSignalStore } from "../store";
import { useSettingsStore } from "../../settings/store";

export function useSignalWebSocket() {
  const { addSignal, setConnected } = useSignalStore();
  const { pairs, timeframes, threshold } = useSettingsStore();
  const wsRef = useRef<WebSocketManager | null>(null);
  const thresholdRef = useRef(threshold);
  thresholdRef.current = threshold;

  useEffect(() => {
    const params = new URLSearchParams();
    if (API_KEY) params.set("api_key", API_KEY);
    const qs = params.toString();

    const ws = new WebSocketManager(
      `${WS_BASE_URL}/ws/signals${qs ? `?${qs}` : ""}`,
    );
    wsRef.current = ws;

    ws.onConnected = () => {
      setConnected(true);
      ws.send(JSON.stringify({ type: "subscribe", pairs, timeframes }));
    };

    ws.onDisconnected = () => setConnected(false);

    ws.onMessage = (data: any) => {
      if (
        data.type === "signal" &&
        Math.abs(data.signal.final_score) >= thresholdRef.current
      ) {
        addSignal(data.signal);
      }
    };

    ws.connect();
    return () => ws.disconnect();
  }, [pairs, timeframes, addSignal, setConnected]);

  return wsRef;
}
```

**Step 2: Implement ConnectionStatus indicator**

`web/src/features/signals/components/ConnectionStatus.tsx`:

```tsx
import { useSignalStore } from "../store";

export function ConnectionStatus() {
  const connected = useSignalStore((s) => s.connected);

  return (
    <div className="flex items-center gap-2 text-xs text-gray-400">
      <div
        className={`w-2 h-2 rounded-full ${connected ? "bg-long" : "bg-short animate-pulse"}`}
      />
      {connected ? "Live" : "Reconnecting..."}
    </div>
  );
}
```

**Step 3: Implement SignalFeed page**

`web/src/features/signals/components/SignalFeed.tsx`:

```tsx
import { useSignalStore } from "../store";
import { useSignalWebSocket } from "../hooks/useSignalWebSocket";
import { SignalCard } from "./SignalCard";
import { SignalDetail } from "./SignalDetail";
import { ConnectionStatus } from "./ConnectionStatus";

export function SignalFeed() {
  useSignalWebSocket();
  const { signals, selectedSignal, selectSignal, clearSelection } =
    useSignalStore();

  return (
    <div className="p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold">Signals</h1>
        <ConnectionStatus />
      </div>

      {signals.length === 0 ? (
        <p className="text-gray-500 text-center mt-12">
          Waiting for signals...
        </p>
      ) : (
        <div className="space-y-3">
          {signals.map((signal) => (
            <SignalCard
              key={signal.id}
              signal={signal}
              onSelect={selectSignal}
            />
          ))}
        </div>
      )}

      <SignalDetail signal={selectedSignal} onClose={clearSelection} />
    </div>
  );
}
```

**Step 4: Wire up App**

Replace `web/src/App.tsx`:

```tsx
import { Layout } from "./shared/components/Layout";
import { SignalFeed } from "./features/signals/components/SignalFeed";

function SettingsPlaceholder() {
  return <div className="p-4 text-gray-400">Settings coming soon...</div>;
}

export default function App() {
  return <Layout feed={<SignalFeed />} settings={<SettingsPlaceholder />} />;
}
```

**Step 5: Verify it renders**

```bash
cd web && npm run dev
```

Expected: Signal feed with "Signals" header, connection status indicator (red pulsing "Reconnecting..." since backend WS isn't running yet), empty state message.

**Step 6: Commit**

```bash
git add web/src/features/signals/ web/src/App.tsx
git commit -m "feat(web): add signal feed with WebSocket hook, card, and detail dialog"
```

---

### Task 10: Settings Page

**Files:**
- Create: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/src/App.tsx`

**Step 1: Implement SettingsPage**

`web/src/features/settings/components/SettingsPage.tsx`:

```tsx
import { useSettingsStore } from "../store";
import { AVAILABLE_PAIRS } from "../../../shared/lib/constants";
import type { Timeframe } from "../../signals/types";

const TIMEFRAMES: Timeframe[] = ["15m", "1h", "4h"];

export function SettingsPage() {
  const {
    pairs,
    timeframes,
    threshold,
    notificationsEnabled,
    apiBaseUrl,
    setPairs,
    setTimeframes,
    setThreshold,
    setNotificationsEnabled,
    setApiBaseUrl,
  } = useSettingsStore();

  const togglePair = (pair: string) => {
    if (pairs.includes(pair)) {
      if (pairs.length > 1) setPairs(pairs.filter((p) => p !== pair));
    } else {
      setPairs([...pairs, pair]);
    }
  };

  const toggleTimeframe = (tf: Timeframe) => {
    if (timeframes.includes(tf)) {
      if (timeframes.length > 1) setTimeframes(timeframes.filter((t) => t !== tf));
    } else {
      setTimeframes([...timeframes, tf]);
    }
  };

  return (
    <div className="p-4 space-y-6">
      <h1 className="text-xl font-bold">Settings</h1>

      {/* Pairs */}
      <section>
        <h2 className="text-sm text-gray-400 mb-2">Trading Pairs</h2>
        <div className="space-y-2">
          {AVAILABLE_PAIRS.map((pair) => (
            <label
              key={pair}
              className="flex items-center gap-3 p-3 bg-card rounded-lg cursor-pointer"
            >
              <input
                type="checkbox"
                checked={pairs.includes(pair)}
                onChange={() => togglePair(pair)}
                className="accent-long w-4 h-4"
              />
              <span>{pair}</span>
            </label>
          ))}
        </div>
      </section>

      {/* Timeframes */}
      <section>
        <h2 className="text-sm text-gray-400 mb-2">Timeframes</h2>
        <div className="flex gap-2">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => toggleTimeframe(tf)}
              className={`px-4 py-2 rounded-lg text-sm transition-colors ${
                timeframes.includes(tf)
                  ? "bg-long/20 text-long border border-long/30"
                  : "bg-card text-gray-400 border border-gray-800"
              }`}
            >
              {tf}
            </button>
          ))}
        </div>
      </section>

      {/* Threshold */}
      <section>
        <h2 className="text-sm text-gray-400 mb-2">
          Alert Threshold: <span className="text-white font-mono">{threshold}</span>
        </h2>
        <input
          type="range"
          min={0}
          max={100}
          value={threshold}
          onChange={(e) => setThreshold(Number(e.target.value))}
          className="w-full accent-long"
        />
        <div className="flex justify-between text-xs text-gray-500 mt-1">
          <span>All signals</span>
          <span>Strong only</span>
        </div>
      </section>

      {/* Notifications */}
      <section>
        <label className="flex items-center justify-between p-3 bg-card rounded-lg cursor-pointer">
          <span>Push Notifications</span>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            onChange={(e) => setNotificationsEnabled(e.target.checked)}
            className="accent-long w-4 h-4"
          />
        </label>
      </section>

      {/* API URL */}
      <section>
        <h2 className="text-sm text-gray-400 mb-2">API Base URL</h2>
        <input
          type="url"
          value={apiBaseUrl}
          onChange={(e) => setApiBaseUrl(e.target.value)}
          className="w-full p-3 bg-card rounded-lg border border-gray-800 text-sm font-mono focus:border-long/50 focus:outline-none"
        />
      </section>
    </div>
  );
}
```

**Step 2: Wire into App**

Replace `web/src/App.tsx`:

```tsx
import { Layout } from "./shared/components/Layout";
import { SignalFeed } from "./features/signals/components/SignalFeed";
import { SettingsPage } from "./features/settings/components/SettingsPage";

export default function App() {
  return <Layout feed={<SignalFeed />} settings={<SettingsPage />} />;
}
```

**Step 3: Verify it renders**

```bash
cd web && npm run dev
```

Expected: Settings page shows pair checkboxes, timeframe buttons, threshold slider, notification toggle, and API URL input. All controls are interactive and persist across tab switches.

**Step 4: Commit**

```bash
git add web/src/features/settings/components/ web/src/App.tsx
git commit -m "feat(web): add settings page with pair, timeframe, threshold, and notification controls"
```

---

### Task 11: PWA Configuration and Icons

**Files:**
- Create: `web/public/icon-192.png`
- Create: `web/public/icon-512.png`

**Step 1: Generate placeholder icons**

Create simple SVG-based PNG placeholder icons. Use any tool or online generator. The icon should be a dark background with "K" or a lightning bolt.

For now, create minimal placeholder PNGs:

```bash
cd web
# use a simple approach - create SVG then convert, or use a placeholder
# if ImageMagick is available:
# magick -size 192x192 xc:#121212 -fill "#22C55E" -font Arial -pointsize 120 -gravity center -annotate 0 "K" public/icon-192.png
# magick -size 512x512 xc:#121212 -fill "#22C55E" -font Arial -pointsize 300 -gravity center -annotate 0 "K" public/icon-512.png

# alternatively, copy any 192x192 and 512x512 PNG as placeholder
# the actual icon design is not critical for MVP
```

If no image tools are available, create a minimal HTML file, screenshot it, or skip icons for now — the PWA will still work without custom icons.

**Step 2: Verify PWA manifest generation**

```bash
cd web && npm run build
```

Check that `dist/manifest.webmanifest` exists and contains the icon references.

Expected: Build succeeds, manifest file generated with correct `name`, `theme_color`, and icon entries.

**Step 3: Verify service worker registration**

```bash
cd web && npm run preview
```

Open in Chrome, check DevTools > Application > Service Workers. Expected: Service worker registered and active.

**Step 4: Commit**

```bash
git add web/public/
git commit -m "feat(web): add PWA icons and verify manifest generation"
```

---

### Task 12: Backend CORS and API Endpoints

> **Note:** This task creates the API surface (REST + WebSocket). Wiring signal engine output to `ConnectionManager.broadcast_signal()` is handled by `backend-d-api-integration.md`. API key auth middleware is also added there -- endpoints are unprotected until then.

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/api/signals.py`
- Create: `backend/app/api/ws.py`
- Create: `backend/app/api/connections.py`
- Create: `backend/tests/api/__init__.py`
- Create: `backend/tests/api/conftest.py`
- Create: `backend/tests/api/test_signals.py`
- Create: `backend/tests/api/test_ws.py`

**Prerequisite:** Ensure a `krypton_test` PostgreSQL database exists:

```bash
docker exec -it krypton-postgres-1 psql -U krypton -c "CREATE DATABASE krypton_test;"
```

**Step 1: Write failing REST signal endpoint test**

`backend/tests/api/__init__.py`: empty file.

`backend/tests/api/conftest.py` (shared fixtures for all API tests):

```python
import os
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings
from app.db.database import Base
from app.main import create_app

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://krypton:krypton@localhost:5432/krypton_test",
)

os.environ.setdefault("KRYPTON_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")


@pytest.fixture
def app():
    @asynccontextmanager
    async def test_lifespan(app):
        engine = create_async_engine(TEST_DATABASE_URL, echo=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        session_factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        app.state.settings = Settings()
        app.state.session_factory = session_factory
        yield
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    return create_app(lifespan_override=test_lifespan)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
```

`backend/tests/api/test_signals.py`:

```python
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import Signal


@pytest.fixture
async def seed_signals(app):
    """Seed test signals into the database."""
    async with app.state.session_factory() as session:
        for i in range(3):
            signal = Signal(
                pair="BTC-USDT-SWAP",
                timeframe="1h",
                direction="LONG",
                final_score=70 + i,
                traditional_score=65 + i,
                llm_opinion="confirm",
                llm_confidence="HIGH",
                explanation="Strong uptrend",
                entry=Decimal("85000"),
                stop_loss=Decimal("84000"),
                take_profit_1=Decimal("87000"),
                take_profit_2=Decimal("89000"),
                created_at=datetime(2026, 2, 27, 12, i, 0, tzinfo=timezone.utc),
            )
            session.add(signal)
        await session.commit()


@pytest.mark.asyncio
async def test_get_signals_empty(client):
    resp = await client.get("/api/signals")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_signals_returns_data(client, seed_signals):
    resp = await client.get("/api/signals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert data[0]["pair"] == "BTC-USDT-SWAP"
    assert data[0]["direction"] == "LONG"
    assert "levels" in data[0]


@pytest.mark.asyncio
async def test_get_signals_filter_pair(client, seed_signals):
    resp = await client.get("/api/signals?pair=ETH-USDT-SWAP")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_signals_limit(client, seed_signals):
    resp = await client.get("/api/signals?limit=2")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
```

**Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/api/test_signals.py -v
```

Expected: FAIL — modules don't exist. Install test dependency if needed:

```bash
pip install httpx
```

**Step 3: Implement CORS middleware and signal endpoint**

Modify `backend/app/main.py` — add CORS and include routers:

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.db.database import Database


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    db = Database(settings.database_url)
    app.state.settings = settings
    app.state.db = db
    app.state.session_factory = db.session_factory
    yield
    await db.close()


def create_app(lifespan_override=None) -> FastAPI:
    app = FastAPI(title="Krypton", version="0.1.0", lifespan=lifespan_override or lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.api.signals import router as signals_router
    from app.api.ws import router as ws_router

    app.include_router(signals_router)
    app.include_router(ws_router)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
```

Create `backend/app/api/__init__.py`: empty file.

Create `backend/app/api/signals.py`:

```python
from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from app.db.models import Signal

router = APIRouter(prefix="/api")


@router.get("/signals")
async def get_signals(
    request: Request,
    pair: str | None = None,
    timeframe: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    async with request.app.state.session_factory() as session:
        stmt = select(Signal).order_by(Signal.created_at.desc()).limit(limit)

        if pair:
            stmt = stmt.where(Signal.pair == pair)
        if timeframe:
            stmt = stmt.where(Signal.timeframe == timeframe)

        result = await session.execute(stmt)
        rows = result.scalars().all()

    return [_serialize_signal(row) for row in rows]


def _serialize_signal(row: Signal) -> dict:
    return {
        "id": row.id,
        "pair": row.pair,
        "timeframe": row.timeframe,
        "direction": row.direction,
        "final_score": row.final_score,
        "traditional_score": row.traditional_score,
        "confidence": row.llm_confidence or "LOW",
        "llm_opinion": row.llm_opinion,
        "explanation": row.explanation,
        "levels": {
            "entry": float(row.entry),
            "stop_loss": float(row.stop_loss),
            "take_profit_1": float(row.take_profit_1),
            "take_profit_2": float(row.take_profit_2),
        },
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/api/test_signals.py -v
```

Expected: All 4 tests PASS.

**Step 5: Write WebSocket connection manager**

`backend/app/api/connections.py`:

```python
from fastapi import WebSocket


class ConnectionManager:
    def __init__(self):
        self.connections: dict[WebSocket, dict] = {}

    async def connect(self, ws: WebSocket, pairs: list[str], timeframes: list[str]):
        await ws.accept()
        self.connections[ws] = {"pairs": pairs, "timeframes": timeframes}

    def disconnect(self, ws: WebSocket):
        self.connections.pop(ws, None)

    def update_subscription(self, ws: WebSocket, pairs: list[str], timeframes: list[str]):
        if ws in self.connections:
            self.connections[ws] = {"pairs": pairs, "timeframes": timeframes}

    async def broadcast_signal(self, signal: dict):
        for ws, sub in list(self.connections.items()):
            if signal["pair"] in sub["pairs"] and signal["timeframe"] in sub["timeframes"]:
                try:
                    await ws.send_json({"type": "signal", "signal": signal})
                except Exception:
                    self.disconnect(ws)


manager = ConnectionManager()
```

**Step 6: Implement WebSocket endpoint**

`backend/app/api/ws.py`:

```python
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.connections import manager

router = APIRouter()


@router.websocket("/ws/signals")
async def signal_stream(websocket: WebSocket):
    default_pairs = ["BTC-USDT-SWAP", "ETH-USDT-SWAP"]
    default_timeframes = ["15m", "1h", "4h"]

    await manager.connect(websocket, default_pairs, default_timeframes)

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if msg.get("type") == "subscribe":
                pairs = msg.get("pairs", default_pairs)
                timeframes = msg.get("timeframes", default_timeframes)
                manager.update_subscription(websocket, pairs, timeframes)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
```

**Step 7: Write WebSocket endpoint test**

`backend/tests/api/test_ws.py`:

```python
from starlette.testclient import TestClient


def test_websocket_connects_and_receives_subscription(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/signals") as ws:
        ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')
        # if we reach here without exception, connection and subscribe succeeded


def test_websocket_handles_malformed_json(app):
    client = TestClient(app)
    with client.websocket_connect("/ws/signals") as ws:
        ws.send_text("not-json")
        # should not crash — connection stays open
        ws.send_text('{"type": "subscribe", "pairs": ["BTC-USDT-SWAP"], "timeframes": ["1h"]}')
```

**Step 8: Run all backend tests**

```bash
cd backend && python -m pytest tests/api/ -v
```

Expected: All 6 tests PASS.

**Step 9: Commit**

```bash
git add backend/app/api/ backend/app/main.py backend/tests/api/ backend/tests/api/conftest.py
git commit -m "feat(backend): add CORS, REST /api/signals, and WebSocket /ws/signals endpoints"
```

---

### Task 13: Backend Push Notification Support

> **Note:** `dispatch_push_for_signal()` is implemented here but wired into the signal pipeline by `backend-d-api-integration.md`.

**Files:**
- Modify: `backend/app/db/models.py`
- Modify: `backend/app/config.py`
- Create: `backend/app/api/push.py`
- Create: `backend/app/push/__init__.py`
- Create: `backend/app/push/dispatch.py`
- Create: `backend/tests/api/test_push.py`
- Modify: `backend/requirements.txt`

**Step 1: Add pywebpush dependency**

```bash
cd backend && pip install pywebpush && pip freeze | grep -i pywebpush
```

Add `pywebpush` to `requirements.txt`.

**Step 2: Add VAPID config to Settings**

Modify `backend/app/config.py` — add these fields to the `Settings` class:

```python
    # push notifications
    vapid_private_key: str = ""
    vapid_claims_email: str = ""
    vapid_public_key: str = ""
```

**Step 3: Add PushSubscription model**

Add to `backend/app/db/models.py`:

```python
from sqlalchemy import ARRAY  # add to imports if not present


class PushSubscription(Base):
    __tablename__ = "push_subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    endpoint: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    p256dh_key: Mapped[str] = mapped_column(String(128), nullable=False)
    auth_key: Mapped[str] = mapped_column(String(64), nullable=False)
    pairs: Mapped[list] = mapped_column(JSONB, nullable=False)
    timeframes: Mapped[list] = mapped_column(JSONB, nullable=False)
    threshold: Mapped[int] = mapped_column(Integer, default=50)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
```

Note: Uses JSONB for the pairs/timeframes arrays since PostgreSQL `ARRAY` types don't work with SQLite in tests. JSONB is already imported.

**Step 4: Create Alembic migration**

```bash
cd backend && alembic revision --autogenerate -m "add push_subscriptions table"
```

Expected: New migration file created in `alembic/versions/`.

**Step 5: Write failing push endpoint tests**

`backend/tests/api/test_push.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_subscribe_creates_subscription(client):
    resp = await client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example.com/abc",
            "keys": {"p256dh": "key123", "auth": "auth456"},
            "pairs": ["BTC-USDT-SWAP"],
            "timeframes": ["1h"],
            "threshold": 60,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "subscribed"


@pytest.mark.asyncio
async def test_subscribe_upserts_on_duplicate_endpoint(client):
    payload = {
        "endpoint": "https://push.example.com/abc",
        "keys": {"p256dh": "key123", "auth": "auth456"},
        "pairs": ["BTC-USDT-SWAP"],
        "timeframes": ["1h"],
        "threshold": 60,
    }
    await client.post("/api/push/subscribe", json=payload)

    payload["threshold"] = 80
    resp = await client.post("/api/push/subscribe", json=payload)
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_unsubscribe_removes_subscription(client):
    await client.post(
        "/api/push/subscribe",
        json={
            "endpoint": "https://push.example.com/abc",
            "keys": {"p256dh": "key123", "auth": "auth456"},
            "pairs": ["BTC-USDT-SWAP"],
            "timeframes": ["1h"],
            "threshold": 60,
        },
    )
    resp = await client.post(
        "/api/push/unsubscribe",
        json={"endpoint": "https://push.example.com/abc"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "unsubscribed"
```

**Step 6: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/api/test_push.py -v
```

Expected: FAIL — push module doesn't exist.

**Step 7: Implement push endpoints**

`backend/app/api/push.py`:

```python
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import delete, select

from app.db.models import PushSubscription

router = APIRouter(prefix="/api/push")


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: dict
    pairs: list[str]
    timeframes: list[str]
    threshold: int = 50


class UnsubscribeRequest(BaseModel):
    endpoint: str


@router.post("/subscribe")
async def subscribe(req: SubscribeRequest, request: Request):
    async with request.app.state.session_factory() as session:
        # upsert: delete existing then insert
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        )
        sub = PushSubscription(
            endpoint=req.endpoint,
            p256dh_key=req.keys["p256dh"],
            auth_key=req.keys["auth"],
            pairs=req.pairs,
            timeframes=req.timeframes,
            threshold=req.threshold,
        )
        session.add(sub)
        await session.commit()

    return {"status": "subscribed"}


@router.post("/unsubscribe")
async def unsubscribe(req: UnsubscribeRequest, request: Request):
    async with request.app.state.session_factory() as session:
        await session.execute(
            delete(PushSubscription).where(PushSubscription.endpoint == req.endpoint)
        )
        await session.commit()

    return {"status": "unsubscribed"}
```

**Step 8: Register push router in main.py**

Add to the `create_app` function in `backend/app/main.py`:

```python
    from app.api.push import router as push_router
    app.include_router(push_router)
```

**Step 9: Implement push dispatch**

`backend/app/push/__init__.py`: empty file.

`backend/app/push/dispatch.py`:

```python
import asyncio
import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models import PushSubscription

logger = logging.getLogger(__name__)


async def dispatch_push_for_signal(
    session_factory: async_sessionmaker,
    signal: dict,
    vapid_private_key: str,
    vapid_claims_email: str,
):
    """Send push notifications to all matching subscriptions for a signal."""
    if not vapid_private_key:
        return

    async with session_factory() as session:
        result = await session.execute(select(PushSubscription))
        subscriptions = result.scalars().all()

    for sub in subscriptions:
        if signal["pair"] not in sub.pairs:
            continue
        if signal["timeframe"] not in sub.timeframes:
            continue
        if abs(signal["final_score"]) < sub.threshold:
            continue

        payload = json.dumps({
            "title": f"{signal['direction']} {signal['pair']}",
            "body": f"Score: {signal['final_score']} | {signal['timeframe']}",
            "url": "/",
        })

        try:
            await asyncio.to_thread(
                webpush,
                subscription_info={
                    "endpoint": sub.endpoint,
                    "keys": {"p256dh": sub.p256dh_key, "auth": sub.auth_key},
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_claims_email},
            )
        except WebPushException as e:
            logger.warning("Push failed for %s: %s", sub.endpoint, e)
```

**Step 10: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/api/test_push.py -v
```

Expected: All 3 tests PASS.

**Step 11: Run all backend tests**

```bash
cd backend && python -m pytest -v
```

Expected: All tests PASS (existing + new).

**Step 12: Commit**

```bash
git add backend/app/api/push.py backend/app/push/ backend/app/db/models.py backend/app/config.py backend/app/main.py backend/tests/api/test_push.py backend/requirements.txt
git commit -m "feat(backend): add push notification support with subscribe/unsubscribe endpoints"
```

---

### Task 14: Frontend Push Notification Integration

**Files:**
- Create: `web/src/shared/lib/push.ts`
- Modify: `web/src/features/settings/components/SettingsPage.tsx`
- Modify: `web/vite.config.ts` (switch to injectManifest for custom SW)
- Create: `web/src/sw.ts`

**Step 1: Switch PWA to injectManifest strategy**

The `generateSW` strategy auto-generates a service worker but doesn't support custom push event handlers. Switch to `injectManifest` which lets us write our own service worker.

Update `web/vite.config.ts`:

```typescript
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      strategies: "injectManifest",
      srcDir: "src",
      filename: "sw.ts",
      registerType: "autoUpdate",
      manifest: {
        name: "Krypton",
        short_name: "Krypton",
        description: "AI-enhanced crypto signal copilot",
        theme_color: "#121212",
        background_color: "#121212",
        display: "standalone",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
        ],
      },
      injectManifest: {
        globPatterns: ["**/*.{js,css,html,ico,png,svg}"],
      },
    }),
  ],
  test: {
    globals: true,
    environment: "jsdom",
  },
});
```

**Step 2: Create custom service worker**

`web/src/sw.ts`:

```typescript
/// <reference lib="webworker" />
import { precacheAndRoute } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope;

// workbox precaching (manifest injected by vite-plugin-pwa)
precacheAndRoute(self.__WB_MANIFEST);

// push notification handler
self.addEventListener("push", (event) => {
  if (!event.data) return;

  const data = event.data.json();
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: "/icon-192.png",
      badge: "/icon-192.png",
      data: { url: data.url || "/" },
    }),
  );
});

// notification click — focus or open the app
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = event.notification.data?.url || "/";

  event.waitUntil(
    self.clients.matchAll({ type: "window" }).then((windowClients) => {
      for (const client of windowClients) {
        if (client.url.includes(self.location.origin) && "focus" in client) {
          return client.focus();
        }
      }
      return self.clients.openWindow(url);
    }),
  );
});
```

**Step 3: Implement push subscription helper**

`web/src/shared/lib/push.ts`:

```typescript
import { API_BASE_URL, API_KEY, VAPID_PUBLIC_KEY } from "./constants";

export async function subscribeToPush(
  pairs: string[],
  timeframes: string[],
  threshold: number,
): Promise<boolean> {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    return false;
  }

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return false;

  const registration = await navigator.serviceWorker.ready;

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToUint8Array(VAPID_PUBLIC_KEY),
  });

  const keys = subscription.toJSON().keys!;

  await fetch(`${API_BASE_URL}/api/push/subscribe`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
    },
    body: JSON.stringify({
      endpoint: subscription.endpoint,
      keys: { p256dh: keys.p256dh, auth: keys.auth },
      pairs,
      timeframes,
      threshold,
    }),
  });

  return true;
}

export async function unsubscribeFromPush(): Promise<void> {
  if (!("serviceWorker" in navigator)) return;

  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();

  if (subscription) {
    await fetch(`${API_BASE_URL}/api/push/unsubscribe`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(API_KEY ? { "X-API-Key": API_KEY } : {}),
      },
      body: JSON.stringify({ endpoint: subscription.endpoint }),
    });

    await subscription.unsubscribe();
  }
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding)
    .replace(/-/g, "+")
    .replace(/_/g, "/");
  const rawData = window.atob(base64);
  return Uint8Array.from([...rawData].map((c) => c.charCodeAt(0)));
}
```

**Step 4: Add push toggle to SettingsPage**

Update the notifications section in `web/src/features/settings/components/SettingsPage.tsx`. Replace the existing `<section>` for notifications:

```tsx
import { useState } from "react";
import { subscribeToPush, unsubscribeFromPush } from "../../../shared/lib/push";

// inside SettingsPage component, add state:
const [pushStatus, setPushStatus] = useState<"idle" | "subscribing" | "error">("idle");

// replace the notifications section:
      {/* Notifications */}
      <section>
        <label className="flex items-center justify-between p-3 bg-card rounded-lg cursor-pointer">
          <div>
            <span>Push Notifications</span>
            {pushStatus === "error" && (
              <p className="text-xs text-short mt-1">Permission denied or not supported</p>
            )}
          </div>
          <input
            type="checkbox"
            checked={notificationsEnabled}
            disabled={pushStatus === "subscribing"}
            onChange={async (e) => {
              const enabled = e.target.checked;
              setNotificationsEnabled(enabled);
              if (enabled) {
                setPushStatus("subscribing");
                const ok = await subscribeToPush(pairs, timeframes, threshold);
                setPushStatus(ok ? "idle" : "error");
                if (!ok) setNotificationsEnabled(false);
              } else {
                await unsubscribeFromPush();
              }
            }}
            className="accent-long w-4 h-4"
          />
        </label>
      </section>
```

**Step 5: Verify build still works**

```bash
cd web && npm run build
```

Expected: Build succeeds. The service worker is compiled from `src/sw.ts`.

**Step 6: Commit**

```bash
git add web/src/sw.ts web/src/shared/lib/push.ts web/src/features/settings/components/SettingsPage.tsx web/vite.config.ts
git commit -m "feat(web): add push notification support with service worker and subscription flow"
```

---

### Task 15: Delete Mobile App

**Files:**
- Delete: `mobile/` directory

**Step 1: Remove mobile directory**

```bash
rm -rf mobile/
```

**Step 2: Verify nothing references it**

```bash
grep -r "mobile" docker-compose.yml
```

Expected: No references to `mobile/` in docker-compose or other config files.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove React Native mobile app (replaced by PWA)"
```

---

## Setup Notes

### VAPID Key Generation

Before push notifications work, generate VAPID keys once:

```bash
npx web-push generate-vapid-keys
```

This outputs a public key and private key. Add to environment:

- Backend `.env`: `VAPID_PRIVATE_KEY=<private>`, `VAPID_CLAIMS_EMAIL=mailto:you@example.com`, `VAPID_PUBLIC_KEY=<public>`
- Frontend `.env`: `VITE_VAPID_PUBLIC_KEY=<public>`

### Environment Variables

`web/.env` (create for local development):

```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
VITE_API_KEY=your-api-key
VITE_VAPID_PUBLIC_KEY=your-vapid-public-key
```

### Test Database

API tests run against PostgreSQL (not SQLite). Create the test database once:

```bash
docker exec -it krypton-postgres-1 psql -U krypton -c "CREATE DATABASE krypton_test;"
```

Override the URL with `TEST_DATABASE_URL` env var if your setup differs from the default (`postgresql+asyncpg://krypton:krypton@localhost:5432/krypton_test`).
