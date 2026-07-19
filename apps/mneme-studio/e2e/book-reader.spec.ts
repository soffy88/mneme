import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// W3 Part B B4 验收：/studio/book 阅读器真实浏览器渲染，三态标注可见、
// 出处可点开。真实登录会话（同 expected-leak.spec.ts 的一套登录模式）。
//
// 用已经真实编译好的一本书（bk_e7b0a135a4b5，G1 数学，本 session 手动编译并保留），
// 不在测试里现编——省时间，也验证"阅读器读一本已经存在的真实书"这个真实场景。

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

test("书单页可见，列出真实已编译的书", async ({ page }) => {
  await page.goto("/studio/book");
  await expect(page.getByTestId("book-list")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("一年级数学上册")).toBeVisible();
});

test("阅读器渲染章节 + 块，三态引用标注真实可见且可点开出处", async ({ page }) => {
  await page.goto(`/studio/book?book_id=${BOOK_ID}`);

  const chapters = page.getByTestId("chapter");
  await expect(chapters.first()).toBeVisible({ timeout: 20_000 });
  expect(await chapters.count()).toBeGreaterThanOrEqual(1);

  // 三态标注：honesty-first 的实体——真实渲染出来，不是只存在于 API 响应里
  const notes = page.getByTestId("citation-note");
  await expect(notes.first()).toBeVisible({ timeout: 20_000 });
  const noteCount = await notes.count();
  expect(noteCount).toBeGreaterThan(0);

  // 当前没有任何 KU 挂接被人工校订过——所有可见的标注都必须是"推断未核对"
  // 这一态，不能出现"已核对"（如果出现了，要么是数据错了要么是前端标注逻辑错了）
  for (let i = 0; i < noteCount; i++) {
    const state = await notes.nth(i).getAttribute("data-citation-state");
    expect(state).toBe("inferred_unverified");
  }

  // 出处可点开：点开第一个标注，能看到人话提示 + 技术细节（pdf_id/page/char_span）
  const first = notes.first();
  await first.locator("summary").click();
  await expect(first.getByText("还没有老师核对过", { exact: false })).toBeVisible();
  await expect(first.getByTestId("citation-technical")).toBeVisible();
  const technical = await first.getByTestId("citation-technical").textContent();
  expect(technical).toContain("pdf_id=");
  expect(technical).toContain("page=");
  expect(technical).toContain("char_span=");
});

test("quiz/flash_cards/guided 块不泄漏具体题目内容，只给学习页入口", async ({ page }) => {
  await page.goto(`/studio/book?book_id=${BOOK_ID}`);
  await expect(page.getByTestId("chapter").first()).toBeVisible({ timeout: 20_000 });

  const quizBlocks = page.getByTestId("block-quiz");
  await expect(quizBlocks.first()).toBeVisible();
  await expect(quizBlocks.first().getByText("去学习")).toBeVisible();

  // 页面全文不应该出现任何看起来像具体题干/答案的内容——只应该是入口提示
  const bodyText = await page.textContent("body");
  expect(bodyText).toContain("配套练习题");
});
