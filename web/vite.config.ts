/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

import { cloudflare } from "@cloudflare/vite-plugin";

export default defineConfig({
  plugins: [react(), VitePWA({
    strategies: "injectManifest",
    srcDir: "src",
    filename: "sw.ts",
    registerType: "prompt",
    manifest: {
      name: "Krypton",
      short_name: "Krypton",
      description: "AI-enhanced crypto signal copilot",
      theme_color: "#0a0f14",
      background_color: "#0a0f14",
      display: "standalone",
      icons: [
        { src: "/web-app-manifest-192x192.png", sizes: "192x192", type: "image/png", purpose: "any maskable" },
        { src: "/web-app-manifest-512x512.png", sizes: "512x512", type: "image/png", purpose: "any maskable" },
      ],
    },
    injectManifest: {
      globPatterns: ["**/*.{js,css,html,ico,svg}", "web-app-manifest-*.png", "apple-touch-icon.png", "favicon-96x96.png"],
    },
  }), cloudflare()],
  server: {
    watch: {
      usePolling: true,
    },
  },
  test: {
    globals: true,
    environment: "jsdom",
  },
});