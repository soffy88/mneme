// questions.ts —— 拍照提问 / 错题复习 / 做题记录 的 HTTP 客户端。
//
// 与 lib/mcp.ts 同一套约定：同源优先（NEXT_PUBLIC_API_BASE，未设置才回退 localhost）、
// Bearer 取自 getToken()、401 → redirectToLogin()、!ok → throw McpError(status, text)。
// 本文件只做「取数与上传」，不含任何判分/答案逻辑（那些在服务端内核）。

import { getToken, redirectToLogin, McpError } from "@/lib/mcp";

// 与 lib/mcp.ts 逐字一致：绝不能用 `||` —— "" 是生产同源空串，是合法值。
const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

function authHeaders(extra: Record<string, string> = {}): Record<string, string> {
  const token = getToken();
  return { ...extra, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

/** 统一 401 处理 + 错误抛出：只回中文友好的 detail，绝不把 stack 交给调用方渲染。 */
function handleAuthStatus(status: number): void {
  if (status === 401 && typeof window !== "undefined") redirectToLogin();
}

/**
 * 带超时的 fetch。拍照解题可能 5–40s，用 60s；其余 20s。
 * 超时以 AbortError 抛出，由页面翻译成中文提示 + 重试。
 */
async function fetchWithTimeout(
  path: string,
  init: RequestInit,
  timeoutMs: number
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal });
  } catch (e) {
    // 超时 / 断网：给学生看得懂的中文，而不是浏览器的英文异常
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("网络有点慢，等了太久没有回应，请点重试");
    }
    throw new Error("网络连接失败，请检查网络后重试");
  } finally {
    clearTimeout(timer);
  }
}

async function readError(res: Response): Promise<string> {
  const raw = await res.text();
  try {
    const detail = (JSON.parse(raw) as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "提交的内容不合法，检查一下再试。";
  } catch {
    /* 非 JSON 错误体：原样返回 */
  }
  return raw || "请求失败";
}

async function requestJson<T>(
  path: string,
  init: RequestInit,
  timeoutMs: number
): Promise<T> {
  const res = await fetchWithTimeout(path, init, timeoutMs);
  if (!res.ok) {
    handleAuthStatus(res.status);
    throw new McpError(res.status, await readError(res));
  }
  return (await res.json()) as T;
}

function postJson<T>(path: string, payload: unknown, timeoutMs = 20_000): Promise<T> {
  return requestJson<T>(
    path,
    {
      method: "POST",
      headers: authHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    },
    timeoutMs
  );
}

// ── 类型 ────────────────────────────────────────────────────────────────────
export interface OcrInfo {
  engine: "vision" | "ocr" | "typed" | "none";
  ms: number;
  confidence: number | null;
}

export interface AskResult {
  ask_id: string;
  record_id: string;
  text: string;
  subject: string | null;
  grade: string | null;
  has_image: boolean;
  ocr: OcrInfo;
  /** 文字行（带归一化边界框），Server 有能力才有；缺失就走纯文本。 */
  lines?: AskLine[];
  image_w?: number | null;
  image_h?: number | null;
  warning?: string;
}

export type SolveStatus = "ok" | "partial" | "multi" | "no_exact_solver" | "llm_unavailable";

/** provider = 教学引擎（feature-flag）给的讲解；llm = 通用 LLM 兜底。 */
export type SolverKind = "kernel" | "provider" | "llm" | "none";

/** 识别出的文字行 + 归一化到上传图的边界框 [x0,y0,x1,y1]（0..1）。 */
export interface AskLine {
  text: string;
  score: number;
  box: [number, number, number, number];
}

export type AnswerCard =
  | {
      type: "english_word";
      word: string;
      phonetic?: string | null;
      meanings: string[];
      inflections?: Record<string, unknown> | null;
      tags?: string[] | null;
    }
  | {
      type: "poem";
      title: string;
      author: string;
      dynasty: string;
      lines: string[];
      highlight?: number | null;
      answer?: string | null;
    }
  | { type: "pinyin"; items: { char: string; pinyin: string }[] }
  | {
      type: "idiom";
      word: string;
      pinyin?: string | null;
      explanation: string;
      derivation?: string | null;
      example?: string | null;
    };

export interface AskSolveResult {
  ask_id: string;
  status: SolveStatus;
  solver: SolverKind;
  kernel?: string | null;
  hint: string | null;
  steps: string[];
  answer: string | null;
  explanation: string | null;
  latency_ms: number;
  card?: AnswerCard | null;
  /** 内核解的机器可判分答案（answer_kind=num/nums/expr/ineq/text）。 */
  answer_value?: string | null;
  answer_kind?: string | null;
  unit?: string | null;
  /** 实际求解的题面（多题图片选中那一题）。 */
  question_text?: string | null;
}

/** 反馈「这道题算错了」：原因枚举 + 可选备注。 */
export type ReportReason = "识别错了" | "答案错了" | "步骤看不懂" | "其他";

export interface AskFeedbackResult {
  ok: true;
}

export interface AskFollowupResult {
  reply: string;
  status: "ok" | "llm_unavailable";
  solver?: string;
}

export interface WrongbookAddResult {
  wrong_question_id: string;
  created: boolean;
}

export type ReviewAnswerType = "numeric" | "choice" | "text" | "self";

export interface ReviewItem {
  item_id: string;
  subject: string | null;
  question_text: string;
  has_image: boolean;
  image_record_id: string | null;
  answer_type: ReviewAnswerType;
  est_seconds: number;
  review_count: number;
}

export interface ReviewToday {
  session_id: string;
  budget_seconds: number;
  total_due: number;
  streak: number;
  items: ReviewItem[];
}

export interface ReviewAnswerResult {
  item_id: string;
  is_correct: boolean | null;
  needs_self_grade: boolean;
  correct_answer: string | null;
  explanation: string | null;
  grader: string;
  next_due: string | null;
  graduated: boolean;
}

export interface ReviewFinishResult {
  streak: number;
  longest_streak: number;
  remaining_due: number;
  next_due_at: string | null;
  message: string;
  /** 服务端今日合计（新字段，旧服务端没有 → 前端回落客户端计数）。 */
  today_minutes?: number | null;
  today_answered?: number | null;
  today_correct?: number | null;
  today_accuracy?: number | null;
  due_tomorrow?: number | null;
}

export type HistoryResult = "correct" | "wrong" | "unknown";

export interface HistoryItem {
  id: string;
  created_at: string;
  source: string;
  source_label: string;
  subject: string | null;
  question_text: string;
  is_correct: boolean | null;
  grader: string | null;
  has_image: boolean;
  wrong_question_id: string | null;
}

export interface HistoryPage {
  total: number;
  items: HistoryItem[];
}

export interface HistoryDetail {
  id: string;
  created_at: string;
  source: string;
  source_label: string;
  subject: string | null;
  grade: string | null;
  kc_ids: string[];
  question_text: string;
  student_answer: string | null;
  correct_answer: string | null;
  is_correct: boolean | null;
  grader: string | null;
  hints_used: number | null;
  duration_ms: number | null;
  has_image: boolean;
  wrong_question_id: string | null;
  meta: Record<string, unknown>;
}

/** 按北京时间一天的做题统计（GET /v1/questions/summary）。 */
export interface HistorySummaryDay {
  date: string; // YYYY-MM-DD（北京时间）
  count: number;
  graded: number;
  correct: number;
  wrong: number;
  accuracy: number | null;
  minutes?: number | null;
  top_wrong_kcs: { kc_id: string; name?: string | null; count: number }[];
}

export interface HistorySummary {
  days: HistorySummaryDay[];
}

/** 按天统计（北京时区）。服务端没有就返回 null，前端自己从已加载记录里算。 */
export async function historySummary(days = 30): Promise<HistorySummary | null> {
  try {
    return await requestJson<HistorySummary>(
      `/v1/questions/summary?days=${encodeURIComponent(String(days))}`,
      { headers: authHeaders() },
      20_000
    );
  } catch {
    return null; // 老服务端没有这个端点 → 前端本地口径兜底
  }
}

// ── API ─────────────────────────────────────────────────────────────────────
export interface AskInput {
  image?: Blob | null;
  text?: string;
  subject?: string | null;
  grade?: string | null;
}

/** 拍照/输入提问。multipart —— 不要手动设 Content-Type（浏览器要自己带 boundary）。 */
export function askQuestion(input: AskInput): Promise<AskResult> {
  const form = new FormData();
  if (input.image) form.append("image", input.image, "question.jpg");
  if (input.text && input.text.trim()) form.append("text", input.text.trim());
  if (input.subject) form.append("subject", input.subject);
  if (input.grade) form.append("grade", input.grade);
  return requestJson<AskResult>(
    "/v1/questions/ask",
    { method: "POST", headers: authHeaders(), body: form },
    45_000
  );
}

/** 解题。可能 5–40s，故给 60s 超时。 */
export function solveAsk(
  askId: string,
  body: { text: string; subject?: string | null; grade?: string | null; question_index?: number }
): Promise<AskSolveResult> {
  return postJson<AskSolveResult>(
    `/v1/questions/ask/${encodeURIComponent(askId)}/solve`,
    body,
    60_000
  );
}

export function askFeedback(askId: string, understood: boolean): Promise<AskFeedbackResult> {
  return postJson<AskFeedbackResult>(
    `/v1/questions/ask/${encodeURIComponent(askId)}/feedback`,
    { understood }
  );
}

/** 「这道题算错了？」反馈。服务端只记不返回细节，失败不打断学生。 */
export function reportAsk(
  askId: string,
  body: { reason: string; comment?: string | null }
): Promise<{ ok: true }> {
  return postJson<{ ok: true }>(
    `/v1/questions/ask/${encodeURIComponent(askId)}/report`,
    {
      reason: body.reason,
      ...(body.comment && body.comment.trim() ? { comment: body.comment.trim() } : {}),
    }
  );
}

export function askFollowup(askId: string, message: string): Promise<AskFollowupResult> {
  return postJson<AskFollowupResult>(
    `/v1/questions/ask/${encodeURIComponent(askId)}/followup`,
    { message }
  );
}

export function addToWrongbook(recordId: string): Promise<WrongbookAddResult> {
  return postJson<WrongbookAddResult>("/v1/wrongbook/add", { record_id: recordId });
}

/**
 * 题目图片。带 token 取 bytes → blob → object URL（**绝不把 token 放进 URL**）。
 * 调用方负责在不用时 URL.revokeObjectURL。
 */
export async function fetchQuestionImageUrl(recordId: string): Promise<string> {
  const res = await fetchWithTimeout(
    `/v1/questions/records/${encodeURIComponent(recordId)}/image`,
    { headers: authHeaders() },
    20_000
  );
  if (!res.ok) {
    handleAuthStatus(res.status);
    throw new McpError(res.status, await readError(res));
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export function reviewToday(): Promise<ReviewToday> {
  return requestJson<ReviewToday>(
    "/v1/review/today",
    { headers: authHeaders() },
    20_000
  );
}

export function reviewAnswer(body: {
  session_id: string;
  item_id: string;
  answer: string;
  duration_ms: number;
  self_grade?: boolean | null;
}): Promise<ReviewAnswerResult> {
  return postJson<ReviewAnswerResult>("/v1/review/today/answer", body);
}

export function reviewFinish(body: {
  session_id: string;
  answered: number;
  correct: number;
  duration_seconds: number;
}): Promise<ReviewFinishResult> {
  return postJson<ReviewFinishResult>("/v1/review/today/finish", body);
}

export function historyList(params: {
  subject?: string;
  source?: string;
  result?: HistoryResult;
  since?: string;
  until?: string;
  limit?: number;
  offset?: number;
}): Promise<HistoryPage> {
  const p = new URLSearchParams();
  if (params.subject) p.set("subject", params.subject);
  if (params.source) p.set("source", params.source);
  if (params.result) p.set("result", params.result);
  if (params.since) p.set("since", params.since);
  if (params.until) p.set("until", params.until);
  p.set("limit", String(params.limit ?? 20));
  p.set("offset", String(params.offset ?? 0));
  return requestJson<HistoryPage>(
    `/v1/questions/history?${p.toString()}`,
    { headers: authHeaders() },
    20_000
  );
}

export function historyDetail(id: string): Promise<HistoryDetail> {
  return requestJson<HistoryDetail>(
    `/v1/questions/history/${encodeURIComponent(id)}`,
    { headers: authHeaders() },
    20_000
  );
}
