import { defineConfig } from "@playwright/test";

/** Isolated merge-gate browser config — does not touch production :3001. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /immersive\.spec\.ts/,
  timeout: 90_000,
  use: {
    baseURL: process.env.E2E_FRONTEND_BASE || "http://127.0.0.1:3001",
    headless: true
  },
  reporter: [["list"]],
});
