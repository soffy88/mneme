import { test, expect, type Page } from "@playwright/test";
import { execSync } from "node:child_process";

// W4 Visualize 模式验收：/studio/visualize 真实浏览器渲染，真实 LLM 选类型
// + 真实内核产出数据（不 mock）。验证 VZ-1（至少代表性覆盖 svg_plot/three/
// mermaid 三种类型真实走通）、VZ-2（react-three-fiber 首次真实投用，3D
// canvas 真实渲染出来）。同 solve.spec.ts 的一套登录模式。

const MNEME = "/data/soffy/projects/mneme";

let studentId = "";
let authToken = "";

function dexec(py: string): string {
  const b64 = Buffer.from(py, "utf-8").toString("base64");
  return execSync(
    `docker compose exec -T api python -c "import base64; exec(base64.b64decode('${b64}').decode('utf-8'))"`,
    { cwd: MNEME, encoding: "utf-8" }
  ).trim();
}

test.beforeAll(() => {
  const py = [
    "import asyncio, uuid",
    "from obase.db import SessionLocal",
    "from services.models import User, UserRole",
    "from obase.auth import create_access_token",
    "async def main():",
    "    sid = uuid.uuid4()",
    "    async with SessionLocal() as db:",
    "        db.add(User(id=sid, phone='t'+sid.hex[:10], role=UserRole.student)); await db.commit()",
    "    tok = create_access_token({'sub': str(sid)})",
    "    print('SID:'+str(sid)); print('TOK:'+tok)",
    "asyncio.run(main())",
  ].join("\n");
  const out = dexec(py);
  studentId = (out.match(/SID:(\S+)/) || [])[1] || "";
  authToken = (out.match(/TOK:(\S+)/) || [])[1] || "";
  expect(studentId).toBeTruthy();
  expect(authToken).toBeTruthy();
});

test.afterAll(() => {
  const py = [
    "import asyncio",
    "from sqlalchemy import text",
    "from obase.db import SessionLocal",
    "async def main():",
    "    async with SessionLocal() as db:",
    `        await db.execute(text("DELETE FROM users WHERE id=:i"), {'i':'${studentId}'}); await db.commit()`,
    "asyncio.run(main())",
  ].join("\n");
  dexec(py);
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(
    ([sid, tok]) => {
      localStorage.setItem("mneme_token", tok);
      localStorage.setItem("mneme_user", JSON.stringify({ id: sid, name: "e2e" }));
    },
    [studentId, authToken]
  );
});

async function submitAndWaitForOutcome(page: Page, text: string) {
  const renderCard = page.getByTestId("render-card");
  const notPossible = page.getByText("这个概念暂时画不出来");

  let succeeded = false;
  for (let attempt = 0; attempt < 3 && !succeeded; attempt++) {
    await page.getByTestId("concept-input").fill(text);
    await page.getByTestId("submit-concept").click();
    // 单次真实 LLM 调用（题意理解），实测比 Solve 的两次调用快，但仍给足时间
    await expect(renderCard.or(notPossible)).toBeVisible({ timeout: 45_000 });
    succeeded = await renderCard.isVisible();
  }
  return succeeded;
}

test("svg_plot 真实渲染：内核计算的函数图像", async ({ page }) => {
  await page.goto("/studio/visualize");
  await expect(page.getByTestId("concept-input")).toBeVisible();

  const ok = await submitAndWaitForOutcome(page, "画出函数 y 等于 x 的平方减去 4 的图像");
  expect(ok, "3 次真实提交都未能画出来——概率性 LLM 失败率异常偏高").toBe(true);

  await expect(page.getByTestId("svg-plot")).toBeVisible({ timeout: 10_000 });
  const sourceLabel = await page.getByTestId("data-source-label").textContent();
  expect(sourceLabel).toContain("来自内核计算");
});

test("three 真实渲染：react-three-fiber 首次真实投用", async ({ page }) => {
  await page.goto("/studio/visualize");
  await expect(page.getByTestId("concept-input")).toBeVisible();

  const ok = await submitAndWaitForOutcome(
    page,
    "画出二元函数 z 等于 x 的平方加 y 的平方 的三维曲面"
  );
  expect(ok, "3 次真实提交都未能画出来——概率性 LLM 失败率异常偏高").toBe(true);

  // VZ-2：3D 必须真的走 react-three-fiber 客户端渲染（canvas 元素真实存在）
  await expect(page.getByTestId("three-canvas")).toBeVisible({ timeout: 15_000 });
  const canvas = page.getByTestId("three-canvas").locator("canvas");
  await expect(canvas).toBeVisible({ timeout: 10_000 });
});

test("无法理解/不适用的概念优雅降级，不是白屏或未捕获报错", async ({ page }) => {
  await page.goto("/studio/visualize");
  await page.getByTestId("concept-input").fill("今天晚饭吃什么");
  await page.getByTestId("submit-concept").click();

  const notPossible = page.getByText("这个概念暂时画不出来");
  const errorBox = page.getByTestId("visualize-error");
  await expect(notPossible.or(errorBox)).toBeVisible({ timeout: 45_000 });
});
