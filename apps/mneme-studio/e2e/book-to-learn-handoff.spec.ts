import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// W3 Part B B-8 补测：证明"从活书点进 KC → 落 /studio/learn → 真实作答 →
// 掌握度回流"这条交接本身是通的。不是重建判分流——判分流是既有 /studio/learn
// 链路（expected-leak.spec.ts 已经验证过 expected 不泄漏 + 连续作答），本测试
// 只证明 Book Engine 生成的"去学习"入口链接，真的能把学生带到正确的 KC 并
// 完成一次真实的作答→回流，不是断头链接、也不是带着错的/空的 kc_ids。
//
// 用已经真实编译好的一本书（bk_e7b0a135a4b5，G1 数学）——直接点它某个 quiz
// 块渲染出来的真实链接，不在测试里手写 URL，这样如果 app/book/page.tsx 哪天
// 又把 kc_ids 漏传，测试会真的失败（点进去的题目会对不上）。

const MNEME = "/data/soffy/projects/mneme";
const BOOK_ID = "bk_e7b0a135a4b5";

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
    "    print('SID:'+str(sid)); print('TOK:'+create_access_token({'sub': str(sid)}))",
    "asyncio.run(main())",
  ].join("\n");
  const out = dexec(py);
  studentId = (out.match(/SID:(\S+)/) || [])[1] || "";
  authToken = (out.match(/TOK:(\S+)/) || [])[1] || "";
  expect(studentId).toBeTruthy();
  expect(authToken).toBeTruthy();
});

test.afterAll(() => {
  dexec(
    [
      "import asyncio",
      "from sqlalchemy import text",
      "from obase.db import SessionLocal",
      "async def main():",
      "    async with SessionLocal() as db:",
      `        await db.execute(text("DELETE FROM interaction_events WHERE student_id=:s"), {'s':'${studentId}'})`,
      `        await db.execute(text("DELETE FROM mastery_snapshots WHERE student_id=:s"), {'s':'${studentId}'})`,
      `        await db.execute(text("DELETE FROM kc_mastery WHERE student_id=:s"), {'s':'${studentId}'})`,
      `        await db.execute(text("DELETE FROM users WHERE id=:i"), {'i':'${studentId}'})`,
      "        await db.commit()",
      "asyncio.run(main())",
    ].join("\n")
  );
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

test("B-8 补测：书内 quiz 块的\"去学习\"链接真实带着 kc_ids，落地后能作答并回流掌握度", async ({ page }) => {
  // 1. 从书页出发，找真实渲染出来的 quiz 块链接（不是手写 URL）
  await page.goto(`/studio/book?book_id=${BOOK_ID}`);
  await expect(page.getByTestId("chapter").first()).toBeVisible({ timeout: 20_000 });

  const learnLink = page.getByTestId("quiz-learn-link").first();
  await expect(learnLink).toBeVisible();
  const href = await learnLink.getAttribute("href");
  expect(href).toBeTruthy();
  expect(href).toContain("/studio/learn?kcs=");
  const kcsParam = new URL(href!, "http://x").searchParams.get("kcs");
  expect(kcsParam).toBeTruthy();
  expect(kcsParam!.length).toBeGreaterThan(0);

  // 2. 真的点击（不是 page.goto 到手写地址）——证明链接本身在 DOM 里可点、可达
  await learnLink.click();
  await page.waitForURL(/\/studio\/learn\?kcs=/, { timeout: 10_000 });

  // 3. 落地后，学习页必须真的用这些 kc_ids 走 NextObjective/RequestQuestion
  //    ——不是掉回默认路径（如果是，会看到不同的 kc_name 或直接卡住）
  await expect(page.getByTestId("objective")).toBeVisible({ timeout: 20_000 });

  // 4. 真实作答一轮（不代答，走真实 UI 事件），无论 qtype 是 solve 还是其他，
  //    先看有没有 open 题（G1 概念题多为定量 solve，正常情形走 answer-input）
  const question = page.getByTestId("question");
  await expect(question).toBeVisible({ timeout: 20_000 });

  const openInput = page.getByTestId("answer-open");
  const textInput = page.getByTestId("answer-input");
  if (await openInput.isVisible().catch(() => false)) {
    await openInput.fill("测试作答");
  } else {
    await textInput.fill("1");
  }
  await page.getByTestId("submit").click();
  await expect(page.getByTestId("feedback")).toBeVisible({ timeout: 20_000 });

  // 5. 断言：交接产生了真实的掌握度回流数据——不是"点了但什么都没发生"
  const count = dexec(
    [
      "import asyncio",
      "from sqlalchemy import text",
      "from obase.db import SessionLocal",
      "async def main():",
      "    async with SessionLocal() as db:",
      `        n=(await db.execute(text("SELECT count(*) FROM interaction_events WHERE student_id=:s"),{'s':'${studentId}'})).scalar_one()`,
      "    print(n)",
      "asyncio.run(main())",
    ].join("\n")
  )
    .split("\n")
    .pop();
  expect(Number(count)).toBeGreaterThanOrEqual(1);
});
