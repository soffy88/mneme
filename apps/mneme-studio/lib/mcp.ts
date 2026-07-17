// mcp —— mneme-studio 的唯一数据通道：HTTP /mcp/*（tool 面）。零 DB 凭据（FC-5 同理）。
//
// 铁律：前端**不含 PoseQuestion** —— 出题（携带 expected）是 tutor/agent 的服务端职责。
// 前端只「读待答题(prompt，无 expected)」+「提交真人答案」+「读掌握度」。
// expected 永不进入本前端（network / DOM / console）。这是 W3 在守的东西，结构上强制。

// 同源优先：生产 Dockerfile 显式设 NEXT_PUBLIC_API_BASE=""，即用相对 /mcp
// （sxueji.com/mcp → caddy → api，同源无 CORS）。仅当变量整体**未设置**(undefined，
// 本地 dev)才回退 localhost。**绝不能用 ||** —— "" 是 falsy，会把"同源空串"误判成
// 需要回退 → 浏览器打 localhost:8000 → Failed to fetch / ERR_CONNECTION_REFUSED。
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

// ── 一套登录：复用 mneme-web 的会话（同源 localStorage）──────────────────────
// studio 与 mneme-web 同源(sxueji.com)，localStorage 按 origin 共享、跨路径可读。
// 键名与 mneme-web/src/lib/auth-store.ts 对齐：mneme_token(JWT) / mneme_user(档案)。
// studio **不做第二套登录**：无 token → 跳 mneme-web 的 /login（basePath 之外，故用
// window.location 而非 next router）。
const TOKEN_KEY = "mneme_token";
const USER_KEY = "mneme_user";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** 当前登录学生 id（取自 mneme_user；未登录返回 null，不回退任何 mock id）。 */
export function getStudentId(): string | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return (JSON.parse(raw) as { id?: string }).id ?? null;
  } catch {
    return null;
  }
}

/** 跳转到 mneme-web 登录页（同源、basePath 之外）。登录后回跳 studio。 */
export function redirectToLogin(): void {
  if (typeof window === "undefined") return;
  const next = encodeURIComponent(window.location.pathname + window.location.search);
  window.location.href = `/login?next=${next}`;
}

async function call<T>(tool: string, payload: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/mcp/${tool}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    // token 缺失/过期 → 回 mneme-web 登录（一套登录，不弹 studio 自己的登录）。
    if (res.status === 401 && typeof window !== "undefined") {
      redirectToLogin();
    }
    const detail = await res.text();
    throw new McpError(res.status, detail);
  }
  return (await res.json()) as T;
}

export class McpError extends Error {
  constructor(public status: number, public detail: string) {
    super(`MCP ${status}: ${detail}`);
  }
}

// ── 类型（**故意不含 expected 字段**）───────────────────────────────────────
export type NextAction =
  | "answer_pending" | "review" | "probe" | "practice" | "assess" | "complete";

export interface PendingQuestion {
  question_id: string;
  prompt: string;
  qtype: string; // solve|fill|choice|short|open —— 无 expected
}

export interface NextStep {
  action: NextAction;
  kc_id?: string | null;
  kc_name?: string | null;
  kc_type?: string | null;
  has_pending: boolean;
  pending_question?: PendingQuestion; // 无 expected
  review_task?: { kc_id: string; due_at: number; priority: number };
}

export interface Mastery {
  kc_id: string;
  gate_type: string;
  p_learned: number;
  p_learned_lower_bound: number;
  n_obs: number;
  confident: boolean;
  is_mastered: boolean;
  fsrs_due?: number | null;
}

export interface KcInfo {
  kc_id: string;
  name: string;
  gate_type: string;
  prerequisites: string[];
  rubric?: { kc_id: string; dimensions: { name: string; criterion: string; weight: number }[] } | null;
}

export interface GradeResult {
  graded?: boolean;
  is_correct?: boolean;
  verdict_source?: string;
  needs_qualitative?: boolean;
  qualitative?: boolean; // 定性题：由真 verifier 按 rubric 裁决（非确定性判分）
  score?: number; // 定性达标维度加权分 [0,1]
  kc_id?: string;
  error?: string;
}

// 人在环出题（S3-A）：请求下一题。请求只带 kc_id、响应只回 prompt/qtype —— 无 expected。
export interface PosedQuestion {
  question_id?: string;
  prompt?: string;
  qtype?: string;
  source?: string;
  error?: string;
}

// ── 读工具 + 提交（无 PoseQuestion）─────────────────────────────────────────
export const mcp = {
  // 按学生档案拉学习路径（有内容的 KC、按章节序）。studio 加载时取代写死的默认 KC。
  getPath: (studentId: string) =>
    call<{ textbook_id: string; kc_ids: string[] }>("GetPath", {
      student_id: studentId,
    }),

  nextObjective: (studentId: string, kcIds: string[]) =>
    call<NextStep>("NextObjective", { student_id: studentId, kc_ids: kcIds }),

  checkMastery: (studentId: string, kcId: string) =>
    call<Mastery>("CheckMastery", { student_id: studentId, kc_id: kcId }),

  getKcInfo: (kcId: string) => call<KcInfo>("GetKCInfo", { kc_id: kcId }),

  getReviewQueue: (studentId: string, kcIds: string[]) =>
    call<{ review_queue: { kc_id: string; due_at: number; priority: number }[] }>(
      "GetReviewQueue", { student_id: studentId, kc_ids: kcIds }),

  // 人在环 poser 触发：服务端出题（题库优先/LLM 兜底），expected 只存服务端。
  requestQuestion: (studentId: string, kcId: string) =>
    call<PosedQuestion>("RequestQuestion", { student_id: studentId, kc_id: kcId }),

  submitAnswer: (studentId: string, questionId: string, answer: string) =>
    call<GradeResult>("SubmitAnswer", {
      student_id: studentId, question_id: questionId, answer,
    }),

  // 定性桩：真人自我解释 → 服务端 verifier（W2b 装真 provider）→ ReportResult。
  // 前端只传 explanation + 服务端返回的 evidence；不判分、不碰 expected。
  reportResult: (args: {
    studentId: string; kcId: string; questionId?: string;
    isCorrect: boolean; evidence: Record<string, unknown>;
  }) =>
    call<{ recorded: boolean; passed: boolean }>("ReportResult", {
      student_id: args.studentId, kc_id: args.kcId, question_id: args.questionId,
      is_correct: args.isCorrect, verdict_source: "llm_verified", evidence: args.evidence,
    }),
};
