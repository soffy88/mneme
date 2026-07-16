import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// W2b S1 验收：真人 UI 链路可作答（真实点击/输入的 UI 事件，非 qwen 代答）；
// 且 expected 永不出现在任何 /mcp network 响应 / DOM（W3 的前端版）。
//
// 出题（携带 expected=SECRET）由**服务端 harness**（=tutor 角色）做，前端不参与出题。
// SECRET 是投毒金丝雀：只存服务端 gate.pending_question.expected，任何前端可见处出现即失败。

const MNEME = "/data/soffy/projects/mneme";
const SECRET = "LEAKCANARY_SECRET_9x";
const KC = "renjiao-math-g10-a-ku-二次函数的零点";

let studentId = "";

function dexec(py: string): string {
  // base64 传递，规避 shell/python 的引号冲突。
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
    `        await gate_store.pose_question(db, question_id=qid, student_id=sid, kc_id='${KC}', prompt='解 x^2-5x+6=0', expected='${SECRET}', qtype='solve')`,
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

test("真人 UI 链路可作答，且 expected 不泄漏于 network/DOM", async ({ page }) => {
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

  // 题目（prompt，无 expected）渲染
  await expect(page.getByTestId("prompt")).toContainText("解", { timeout: 15_000 });

  // 真实 UI 事件作答（键盘输入 + 点击提交）—— 非脚本代答，是 UI 链路
  await page.getByTestId("answer-input").fill("x=2, x=3");
  await page.getByTestId("submit").click();

  // 反馈可见（链路闭环：SubmitAnswer → 反馈）
  await expect(page.getByTestId("feedback")).toBeVisible({ timeout: 15_000 });

  // 断言 1：SECRET 不在任何 /mcp 响应体
  expect(leaks, `expected 泄漏于响应: ${leaks.join(", ")}`).toHaveLength(0);

  // 断言 2：SECRET 不在 DOM
  expect(await page.content()).not.toContain(SECRET);
});
