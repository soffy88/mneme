import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// W2b S3-A 验收：人在环连续作答链路（真实 UI 事件，非代答）；且 expected 永不出现在任何
// /mcp 响应 / DOM。前端经 RequestQuestion 自动出题（题库/LLM，服务端出题），真人逐题作答。
//
// 首轮用投毒金丝雀 SECRET（服务端 PoseQuestion 一题带 expected=SECRET）验 W3 前端版；
// 其后 RequestQuestion 自动续题（题库），验连续链路。SECRET 只存服务端，任何前端可见处出现即失败。

const MNEME = "/data/soffy/projects/mneme";
const SECRET = "LEAKCANARY_SECRET_9x";
const KC = "renjiao-math-g10-a-ku-二次函数的零点";

let studentId = "";

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
    "from services import gate_store",
    "async def main():",
    "    sid = uuid.uuid4(); qid = 'q-'+uuid.uuid4().hex",
    "    async with SessionLocal() as db:",
    "        db.add(User(id=sid, phone='t'+sid.hex[:10], role=UserRole.student)); await db.flush()",
    `        await gate_store.pose_question(db, question_id=qid, student_id=sid, kc_id='${KC}', prompt='解 x^2-5x+6=0（首轮金丝雀）', expected='${SECRET}', qtype='solve')`,
    "        await db.commit()",
    "    print(str(sid))",
    "asyncio.run(main())",
  ].join("\n");
  studentId = dexec(py).split("\n").pop() || "";
  expect(studentId).toBeTruthy();
});

test.afterAll(() => {
  const py = [
    "import asyncio",
    "from sqlalchemy import text",
    "from obase.db import SessionLocal",
    "from services.purge_service import purge_deleted_users",
    "async def main():",
    "    async with SessionLocal() as db:",
    `        await db.execute(text("UPDATE users SET deleted_at=now()-interval '1 day' WHERE id=:i"), {'i':'${studentId}'}); await db.commit()`,
    "    async with SessionLocal() as db:",
    "        await purge_deleted_users(db, grace_days=0); await db.commit()",
    "asyncio.run(main())",
  ].join("\n");
  dexec(py);
});

test("人在环连续作答（多轮 UI 链路），expected 不泄漏于 network/DOM", async ({ page }) => {
  const leaks: string[] = [];
  page.on("response", async (resp) => {
    if (resp.url().includes("/mcp/")) {
      try {
        const body = await resp.text();
        if (body.includes(SECRET)) leaks.push(resp.url());
      } catch {
        /* ignore */
      }
    }
  });

  await page.goto(`/studio/learn?student=${studentId}&kcs=${encodeURIComponent(KC)}`);

  // 连续 3 轮：题目呈现 → 真实 UI 事件作答 → 提交 → 自动续下一题（不刷新）
  for (let round = 0; round < 3; round++) {
    await expect(page.getByTestId("question")).toBeVisible({ timeout: 20_000 });
    const input = page.getByTestId("answer-input");
    await expect(input).toBeVisible({ timeout: 20_000 });
    await input.fill("x=2, x=3");
    await page.getByTestId("submit").click();
    await expect(page.getByTestId("feedback")).toBeVisible({ timeout: 20_000 });
    // 提交后 answer 清空 = 该轮已处理、正在自动续题
    await expect(input).toHaveValue("", { timeout: 20_000 });
  }

  // 断言 1：SECRET 不在任何 /mcp 响应体
  expect(leaks, `expected 泄漏于响应: ${leaks.join(", ")}`).toHaveLength(0);
  // 断言 2：SECRET 不在 DOM
  expect(await page.content()).not.toContain(SECRET);

  // 断言 3：连续作答真实写库（≥3 条 interaction_events）—— 人在环链路闭环
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
  expect(Number(count)).toBeGreaterThanOrEqual(3);
});
