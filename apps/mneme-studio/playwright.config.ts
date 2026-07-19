import { defineConfig } from "@playwright/test";

// 测试已运行的 studio（next start -p 3001）+ api（/mcp）。
// timeout 90s（原 40s）：W4 solve.spec.ts 走真实两次 LLM 调用（题意理解+讲解）
// 实测 ~35-40s，40s 全局超时下真实调用还没跑完测试本身就先超时了。
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  use: { baseURL: "http://localhost:3001", headless: true },
  reporter: [["list"]],
});
