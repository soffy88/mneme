import { defineConfig } from "@playwright/test";

/** Isolated merge-gate browser config — does not touch production :3001. */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /immersive\.spec\.ts/,
  timeout: 90_000,
  use: { baseURL: "http://127.0.0.1:3102", headless: true },
  reporter: [["list"]],
});
