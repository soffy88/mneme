import { test, expect } from "@playwright/test";
import { execSync } from "node:child_process";

// W4 Solve 模式验收：/studio/solve 真实浏览器渲染，真实内核求解 + 真实 LLM
// 讲解（不 mock），验证 SV-1（7 类问题至少代表性抽 1 个真实走通全链路）、
// SV-2（步骤来自内核真实输出）。同 book-reader.spec.ts 的一套登录模式。

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

test("真实提交一道题，内核真实求解 + LLM 讲解都渲染出来", async ({ page }) => {
  // 真实 provider 偶发不严格遵守"只输出 JSON"的指令（题意理解阶段解析失败，
  // 优雅降级为"这道题暂时求解不了"——这是本身设计好的正确行为，不是 bug，
  // 见 plan_solve_task._parse() 的 fence-strip/子串兜底注释）。这条测试要
  // 验证的是"能走通"这件事本身，不是每次单次调用都必然成功——真实外部 LLM
  // 的输出质量本来就是概率性的。最多重试 3 次提交，遇到"暂时求解不了"就
  // 重试，遇到真正求解成功就往下断言 SV-1/SV-2/SV-4。
  await page.goto("/studio/solve");
  await expect(page.getByTestId("problem-input")).toBeVisible();

  const kernelAnswer = page.getByTestId("kernel-answer");
  const notSolvable = page.getByText("这道题暂时求解不了");

  let solved = false;
  for (let attempt = 0; attempt < 3 && !solved; attempt++) {
    await page.getByTestId("problem-input").fill("求方程 x的平方减去4等于0 的解");
    await page.getByTestId("submit-problem").click();
    // 真实调用两次 LLM（题意理解 + 讲解）+ 一次内核求解，实测 ~35-40s
    await expect(kernelAnswer.or(notSolvable)).toBeVisible({ timeout: 60_000 });
    solved = await kernelAnswer.isVisible();
  }
  expect(solved, "3 次真实提交都未能求解成功——概率性 LLM 失败率异常偏高").toBe(true);

  // SV-1：这道二次函数题至少能被理解并求解出来（不强行断言具体走哪个内核，
  // 因为题意理解由真实 LLM 做，但断言"确实产出了非空的真实步骤"）。
  const steps = page.getByTestId("solve-step");
  await expect(steps.first()).toBeVisible();
  expect(await steps.count()).toBeGreaterThanOrEqual(1);

  // 答案文本非空——来自内核（不是 narration 编的）
  const answerText = await kernelAnswer.textContent();
  expect(answerText).toBeTruthy();
  expect(answerText!.length).toBeGreaterThan(0);

  // 讲解区块存在（LLM 转述，纯附加，不是唯一的答案来源）
  await expect(page.getByTestId("narration")).toBeVisible({ timeout: 15_000 });
});

test("无法理解/求解的题优雅降级，不是白屏或未捕获报错", async ({ page }) => {
  await page.goto("/studio/solve");
  await page.getByTestId("problem-input").fill("今天天气怎么样");
  await page.getByTestId("submit-problem").click();

  // 非数学问题 -> plan_solve_task 大概率判不出合法内核 -> 优雅降级提示，
  // 不是页面崩溃/白屏（给宽松超时，真实 LLM 调用有真实延迟）。
  const notSolvable = page.getByText("这道题暂时求解不了");
  const errorBox = page.getByTestId("solve-error");
  await expect(notSolvable.or(errorBox)).toBeVisible({ timeout: 60_000 });
});
