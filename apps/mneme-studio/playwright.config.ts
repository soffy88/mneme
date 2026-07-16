import { defineConfig } from "@playwright/test";

// 测试已运行的 studio（next start -p 3001）+ api（/mcp）。
export default defineConfig({
  testDir: "./e2e",
  timeout: 40_000,
  use: { baseURL: "http://localhost:3001", headless: true },
  reporter: [["list"]],
});
