// mcp —— mneme-studio 的唯一数据通道：HTTP /mcp/*（tool 面）。零 DB 凭据（FC-5 同理）。
//
// 铁律：前端**不含 PoseQuestion** —— 出题（携带 expected）是 tutor/agent 的服务端职责。
// 前端只「读待答题(prompt，无 expected)」+「提交真人答案」+「读掌握度」。
// expected 永不进入本前端（network / DOM / console）。这是 W3 在守的东西，结构上强制。

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") || "http://localhost:8000";

async function call<T>(tool: string, payload: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}/mcp/${tool}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
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
  kc_id?: string;
  error?: string;
}

// ── 读工具 + 提交（无 PoseQuestion）─────────────────────────────────────────
export const mcp = {
  nextObjective: (studentId: string, kcIds: string[]) =>
    call<NextStep>("NextObjective", { student_id: studentId, kc_ids: kcIds }),

  checkMastery: (studentId: string, kcId: string) =>
    call<Mastery>("CheckMastery", { student_id: studentId, kc_id: kcId }),

  getKcInfo: (kcId: string) => call<KcInfo>("GetKCInfo", { kc_id: kcId }),

  getReviewQueue: (studentId: string, kcIds: string[]) =>
    call<{ review_queue: { kc_id: string; due_at: number; priority: number }[] }>(
      "GetReviewQueue", { student_id: studentId, kc_ids: kcIds }),

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
