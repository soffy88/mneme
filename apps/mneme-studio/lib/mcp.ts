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

async function apiGet<T>(path: string): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

async function apiDelete<T>(path: string): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "DELETE",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

async function apiPost<T>(path: string, payload: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

export interface LearnNowView {
  status: string;
  selected_action?: { action?: string; candidate_id?: string } | null;
  policy_decision_id?: string | null;
  reason_codes: string[];
  evidence_refs: string[];
  why_this: { claim_type?: string; claim_value?: unknown; evidence_refs: string[] }[];
}

export interface ProductProgress {
  activity_progress: { active_minutes: number | null; attempts: number | null; reviews: number | null; learning_days: number | null };
  learning_progress: { retained_mastery?: unknown; retention?: unknown; transfer?: unknown; independent_performance?: unknown; jol_calibration?: unknown; long_term_retention_label: string };
  evidence_mode: string;
}

export type ProductEventType =
  | "content_ready"
  | "learning_session_started"
  | "first_value_completed"
  | "next_best_action_started"
  | "next_best_action_completed"
  | "learning_session_completed"
  | "return_reason_presented"
  | "review_completed"
  | "independent_test_completed";

export class McpError extends Error {
  constructor(public status: number, public detail: string) {
    super(`MCP ${status}: ${detail}`);
  }
}

// 服务端掌握路径锁（RequestQuestion 403 code=path_locked）：学习者请求了 current 之后的
// 未解锁知识点。前端只把服务端给的 current 知识点展示出来，不自行判定锁状态。
export interface PathLockedInfo {
  kc_id: string;
  kc_name: string | null;
  current_kc_id: string | null;
  current_kc_name: string | null;
  message: string;
}

export function pathLockedInfo(e: unknown): PathLockedInfo | null {
  if (!(e instanceof McpError) || e.status !== 403) return null;
  try {
    const d = (JSON.parse(e.detail) as { detail?: unknown }).detail as
      | (Partial<PathLockedInfo> & { code?: string })
      | undefined;
    if (!d || typeof d !== "object" || d.code !== "path_locked") return null;
    return {
      kc_id: String(d.kc_id ?? ""),
      kc_name: d.kc_name ?? null,
      current_kc_id: d.current_kc_id ?? null,
      current_kc_name: d.current_kc_name ?? null,
      message: d.message ?? "这个知识点还没解锁，先完成当前知识点吧。",
    };
  } catch {
    return null;
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

// ── Book Engine（W3 Part B B4）：教材引用三态 —— 分数<0.60 后端已经不返回，
// 前端只需要区分 verified / inferred_unverified 两态，展示成人话，不是给
// 工程师看的技术标签。──────────────────────────────────────────────────────
export type CitationState = "verified" | "inferred_unverified";

export interface BookCitation {
  chunk_id: string;
  pdf_id: string;
  page_number: number | null;
  char_start: number | null;
  char_end: number | null;
  content: string;
  score: number;
  citation_state: CitationState;
  textbook_meta?: { subject?: string; grade?: string; book_name?: string };
}

export type BookBlockType = "text" | "callout" | "figure" | "quiz" | "flash_cards" | "guided";

export interface BookBlock {
  block_id: string;
  block_type: BookBlockType;
  payload: Record<string, unknown>;
  citations: BookCitation[];
  status: string;
}

export interface BookChapter {
  chapter_id: string;
  title: string;
  content_type: string;
  learning_objectives: string[];
  summary: string | null;
  blocks: BookBlock[];
}

export interface BookDetail {
  book_id: string;
  textbook_id: string;
  title: string;
  description: string | null;
  scope: string | null;
  target_level: string | null;
  status: string;
  subject?: string;
  grade?: string;
  book_name?: string;
  chapters: BookChapter[];
}

export interface BookSummary {
  book_id: string;
  textbook_id: string;
  title: string;
  description: string | null;
  status: string;
  subject?: string;
  grade?: string;
  book_name?: string;
}

// ── 活书编译入口：POST /v1/books/compile + GET /v1/books/{id}/status ──────────
export interface CompilableTextbook {
  textbook_id: string;
  subject: string;
  grade: string;
  book_name: string;
  edition: string | null;
  n_clusters: number;
  n_units: number;
  n_books: number;
}

export interface BookCompileJob {
  book_id: string;
  status: string;
  deduplicated: boolean;
}

export interface BookCompileStatus {
  book_id: string;
  textbook_id: string;
  book_name: string | null;
  title: string;
  status: "queued" | "compiling" | "ready" | "partial" | "error" | string;
  stale: boolean;
  error: string | null;
  cost_usd: number;
  n_chapters: number;
  n_blocks: number;
  n_block_errors: number;
  requested_by_me: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export function listCompilableTextbooks(): Promise<{ textbooks: CompilableTextbook[]; daily_limit: number; is_admin: boolean }> {
  return apiGet("/v1/books/compile/textbooks");
}

export function compileBook(textbookId: string): Promise<BookCompileJob> {
  return apiPost<BookCompileJob>("/v1/books/compile", { textbook_id: textbookId });
}

export function bookCompileStatus(bookId: string): Promise<BookCompileStatus> {
  return apiGet<BookCompileStatus>(`/v1/books/${encodeURIComponent(bookId)}/status`);
}

// ── 研究报告（/v1/research）：只检索本地教材库，每条论断带 书/页/切片 出处 ─────
export interface ResearchCitation {
  source_id: string;
  book_name: string | null;
  page_number: number | null;
  chunk_id: string;
  verified: boolean;
}
export interface ResearchPoint {
  text: string;
  sources: string[];
  citations: ResearchCitation[];
  support: "matched" | "weak";
}
export interface ResearchSource {
  id: string;
  chunk_id: string;
  book_name: string | null;
  subject: string | null;
  grade: string | null;
  page_number: number | null;
  score: number | null;
  verified: boolean;
  excerpt: string;
}
export interface ResearchReportBody {
  title: string;
  summary: ResearchPoint | null;
  sections: { heading: string; points: ResearchPoint[] }[];
  unsupported: { text: string; note: string }[];
  gaps: string[];
}
export interface ResearchReport {
  id: string;
  question: string;
  grade: string | null;
  status: "ready" | "extractive" | "no_sources";
  title: string | null;
  created_at: string | null;
  report: ResearchReportBody;
  sources: ResearchSource[];
  model: string | null;
  latency_ms: number;
  error: string | null;
}
export interface ResearchListItem {
  id: string;
  question: string;
  status: string;
  title: string | null;
  created_at: string | null;
}
export interface ResearchList {
  items: ResearchListItem[];
  daily_limit: number;
  used_today: number;
}

export function createResearch(question: string): Promise<ResearchReport> {
  return apiPost<ResearchReport>("/v1/research", { question });
}

export function getResearch(id: string): Promise<ResearchReport> {
  return apiGet<ResearchReport>(`/v1/research/${encodeURIComponent(id)}`);
}

export function listResearch(): Promise<ResearchList> {
  return apiGet<ResearchList>("/v1/research");
}

// ── W4 Solve：自然语言题目 -> 内核真实求解 + LLM 讲解 ─────────────────────
// answer/steps 是 7 个确定性内核（S0 加固后全经沙箱）的真实输出；narration
// 是 LLM 纯附加的自然语言讲解，绝不会替换/覆盖 answer/steps（SV-2/SV-4）。
export interface SolveStep {
  step_number: number;
  description: string;
  expression: string;
  result: string;
}

export interface SolveProblemResult {
  kernel: string;
  task: string;
  restated_problem: string;
  solvable: boolean;
  answer: string;
  steps: SolveStep[];
  error: string;
  narration: string;
}

// ── W4 Visualize：数学概念/数据 -> 真实渲染数据（去 Manim）─────────────────
// data_source 如实标注来源：svg_plot/three/chart 三种类型来自真实内核
// （kernel_to_plot2d/kernel_to_three/solve_sequence，均经 S0 加固沙箱）；
// mermaid 类型是 LLM 直接撰写的声明式图示文本，data_source="llm_authored"，
// 不伪装成内核数据（VZ-4）。
export type VisualizeRenderType = "svg_plot" | "three" | "chart" | "mermaid" | "";

export interface VisualizeConceptResult {
  render_type: VisualizeRenderType;
  restated_concept: string;
  success: boolean;
  error?: string;
  data_source?: string;
  // svg_plot
  svg?: string;
  title?: string;
  // three（客户端用 react-three-fiber 渲染成点云，首次真实投用）
  points?: { x: number[]; y: number[]; z: number[] };
  // chart（react-chartjs-2）
  chart_type?: "line" | "bar";
  labels?: string[];
  datasets?: { label: string; data: number[] }[];
  // mermaid（客户端用 mermaid.js 渲染）
  diagram_source?: string;
}

// ── Memory Inspect（/memory-inspect）：学生本人查看 + 遗忘自己的记忆 ────────────
export type MemoryLayer = "episodic" | "semantic" | "claim";

export interface EpisodicMemoryItem {
  id: string;
  session_id: string | null;
  kind: string;
  content: unknown;
  source_ref: string | null;
  created_at: string | null;
}

export interface SemanticMemoryItem {
  id: string;
  topic: string;
  content: unknown;
  merged_from_count: number;
  updated_at: string | null;
}

export interface MemoryClaimItem {
  id: string;
  claim_type: string;
  subject_type: string;
  subject_id: string;
  knowledge_ref: string | null;
  claim_text: string;
  confidence: number | null;
  evidence_level: string;
  evidence_count: number;
  created_at: string | null;
}

export interface MemoryInspectView {
  student_id: string;
  episodic: EpisodicMemoryItem[];
  semantic: SemanticMemoryItem[];
  claims: MemoryClaimItem[];
}

export interface MemoryEvidenceItem {
  id: string;
  relation: string;
  evidence_type: string;
  knowledge_ref: string | null;
  source: string | null;
  occurred_at: string | null;
  evidence_level: string;
  payload: unknown;
}

// ── Mastery Path（/path）：掌握路径，状态全由服务端内核 is_mastered 派生 ────────
export type PathNodeState = "mastered" | "current" | "locked";

export interface MasteryPathNode {
  kc_id: string;
  name: string;
  kc_type: string;
  state: PathNodeState;
  n_obs: number;
  review_due: boolean;
}

export interface MasteryPathView {
  textbook_id: string;
  status: "completed" | "empty" | "failed";
  nodes: MasteryPathNode[];
  current_kc_id: string | null;
  next: { action: string; kc_id: string | null; kc_name: string | null } | null;
  total_mastered: number;
  total_kps: number;
  pending_review_count: number;
}

// ── Practice（/practice）：FSRS 到期 KC + 本人错题（**不含答案**）──────────────
export interface PracticeKc {
  kc_id: string;
  name: string;
  due_at: string;
  overdue_hours: number;
  wrong_count: number;
  sample_wrong_question: string | null;
}

export interface PracticeWrongQuestion {
  id: string;
  ku_id: string | null;
  ku_name: string | null;
  question_text: string;
  has_image: boolean;
  wrong_count: number;
  last_wrong_at: string | null;
  kc_due: boolean;
  bookmarked?: boolean;
}

// ── 收藏（☆）：题干快照 + KC，**不含答案** ─────────────────────────────────────
export type BookmarkSource = "posed" | "wrong";

export interface QuestionBookmark {
  id: string;
  source: BookmarkSource;
  question_id: string;
  wrong_question_id?: string | null;
  kc_id: string | null;
  kc_name?: string | null;
  prompt: string;
  qtype: string | null;
  created_at: string | null;
  kc_due?: boolean;
}

export interface PracticeQueue {
  student_id: string;
  due_count: number;
  due: PracticeKc[];
  upcoming: PracticeKc[];
  wrong_questions: PracticeWrongQuestion[];
  bookmarks?: QuestionBookmark[];
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

  // W3 Part B B4：活书阅读器。非学生数据，不传 student_id。
  listBooks: () => call<{ books: BookSummary[] }>("ListBooks", {}),

  getBook: (bookId: string) => call<{ book: BookDetail | null }>("GetBook", { book_id: bookId }),

  // W4 Solve：非学生数据，不传 student_id。
  solveProblem: (problemText: string) =>
    call<SolveProblemResult>("SolveProblem", { problem_text: problemText }),

  // W4 Visualize：非学生数据，不传 student_id。
  visualizeConcept: (conceptText: string) =>
    call<VisualizeConceptResult>("VisualizeConcept", { concept_text: conceptText }),

  // Product surfaces are read projections over the same policy/state/event APIs.
  productLearnNow: (studentId: string) => apiGet<LearnNowView>(`/v2/product/learn-now/${studentId}`),
  productFirstValue: (studentId: string) => apiGet<{ stage: string; time_to_first_value_seconds: number | null }>(`/v2/product/first-value/${studentId}`),
  productProgress: (studentId: string) => apiGet<ProductProgress>(`/v2/product/progress/${studentId}`),
  productMemory: (studentId: string) => apiGet<{ items: unknown[]; status: string }>(`/v2/product/memory/${studentId}`),
  productWeakAreas: (studentId: string) => apiGet<{ items: unknown[]; status: string }>(`/v2/product/weak-areas/${studentId}`),
  productReturnReason: (studentId: string) => apiGet<{ return_reason: { reason: string }; notification: { should_send: boolean } }>(`/v2/product/return-reason/${studentId}`),
  productEvent: (studentId: string, eventType: ProductEventType, knowledgeRefs: string[] = [], policyDecisionId?: string) =>
    apiPost<{ event_id: string }>(`/v2/product/events/${studentId}`, {
      event_type: eventType,
      occurred_at: new Date().toISOString(),
      knowledge_refs: knowledgeRefs,
      policy_decision_id: policyDecisionId,
    }),

  // Memory Inspect：仅本人可读/可删（服务端 _ensure_student_self）。
  memoryInspect: (studentId: string) =>
    apiGet<MemoryInspectView>(`/v2/memory/inspect/${studentId}`),
  memoryEvidence: (claimId: string) =>
    apiGet<{ claim: Record<string, unknown>; evidence: MemoryEvidenceItem[] }>(`/v2/memory/evidence/${claimId}`),
  memoryForget: (studentId: string, layer: MemoryLayer, itemId: string) =>
    apiPost<{ forgotten: boolean }>("/v2/memory/forget", {
      student_id: studentId, layer, item_id: itemId,
    }),

  // Mastery Path：只读派生（mastery_path omodul）。前端只渲染状态，不计算掌握度。
  getMasteryPath: (studentId: string) =>
    call<MasteryPathView>("GetMasteryPath", { student_id: studentId }),

  // Practice：只读队列（不含答案）；作答仍走 requestQuestion/submitAnswer。
  practiceQueue: (studentId: string) =>
    apiGet<PracticeQueue>(`/v2/practice/queue/${studentId}`),

  // 收藏（☆）：服务端按归属取题干；前端只传 question_id + 来源。
  addBookmark: (studentId: string, source: BookmarkSource, questionId: string) =>
    apiPost<QuestionBookmark>("/v2/practice/bookmarks", {
      student_id: studentId, source, question_id: questionId,
    }),

  removeBookmark: (bookmarkId: string) =>
    apiDelete<{ deleted: boolean }>(`/v2/practice/bookmarks/${bookmarkId}`),

  listBookmarks: (studentId: string) =>
    apiGet<{ bookmarks: QuestionBookmark[] }>(`/v2/practice/bookmarks/${studentId}`),
};

// ── 交互实验室（确定性教学内核，见 app/lab）────────────────────────────────
async function eduFetch(path: string, payload: unknown, accept: string): Promise<Response> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: accept,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    const raw = await res.text();
    let message = raw;
    try {
      const detail = (JSON.parse(raw) as { detail?: unknown }).detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) message = "题目参数不合法";
    } catch {
      /* 非 JSON 错误体：原样显示 */
    }
    throw new Error(message);
  }
  return res;
}

export async function eduPost<T>(path: string, payload: unknown): Promise<T> {
  return (await (await eduFetch(path, payload, "application/json")).json()) as T;
}

export async function eduPostHtml(path: string, payload: unknown): Promise<string> {
  return (await eduFetch(path, payload, "text/html")).text();
}

// ── 相关实验外链（WeduLab，见 components/RelatedLabs）──────────────────────
export interface RelatedLab {
  slug: string;
  title: string;
  subject: string;
  subject_label: string;
  stages: string[];
  topics: string[];
  url: string;
}

async function relatedGet(path: string): Promise<RelatedLab[]> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`related-labs ${res.status}`);
  const body = (await res.json()) as { labs?: RelatedLab[] };
  // 只接受 https://wedulab.com/labs/ 外链，防御性过滤
  return (body.labs ?? []).filter((l) => typeof l.url === "string" && l.url.startsWith("https://wedulab.com/labs/"));
}

export function fetchRelatedLabs(): Promise<RelatedLab[]> {
  return relatedGet("/v1/related-labs");
}

export function matchRelatedLabs(opts: { q?: string; kcId?: string; subject?: string; limit?: number }): Promise<RelatedLab[]> {
  const p = new URLSearchParams();
  if (opts.q) p.set("q", opts.q.slice(0, 500));
  if (opts.kcId) p.set("kc_id", opts.kcId.slice(0, 64));
  if (opts.subject) p.set("subject", opts.subject);
  p.set("limit", String(opts.limit ?? 3));
  if (!opts.q && !opts.kcId) return Promise.resolve([]);
  return relatedGet(`/v1/related-labs/match?${p.toString()}`);
}

// ── Chat 工作区（/v1/chat/turn：intent_router + tutor_loop）──────────────────
export function chatTurn<T>(payload: unknown): Promise<T> {
  return apiPost<T>("/v1/chat/turn", payload);
}

// ── Immersive Reading（/v1/reading/*）：阅读来源 + 教材原文块 + 本人阅读位置 ─────
// 阅读位置只是进度，不是学习证据；"检查一下"仍走 requestQuestion/submitAnswer，
// "解释这句"仍走 chatTurn —— 前端不新增判分路径。
export type ReadingSourceKind = "book" | "textbook";

export interface ReadingPosition {
  source_kind: ReadingSourceKind;
  source_id: string;
  block_index: number;
  block_id: string | null;
  total_blocks: number | null;
  updated_at: string | null;
}

export interface ReadingTextbookSummary {
  textbook_id: string;
  subject: string;
  grade: string;
  book_name: string;
  n_chunks: number;
  has_book: boolean;
}

export interface ReadingSources {
  books: (BookSummary & { status: string })[];
  textbooks: ReadingTextbookSummary[];
  positions: ReadingPosition[];
}

export interface ReadingBlock {
  block_id: string;
  index: number;
  block_type: "text";
  section_title: string | null;
  page_number: number | null;
  payload: { text: string };
  kc_ids: string[];
}

export interface ReadingTextbookPage {
  textbook: { textbook_id: string; subject: string; grade: string; book_name: string };
  total: number;
  offset: number;
  blocks: ReadingBlock[];
}

async function apiPut<T>(path: string, payload: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

export function readingSources(): Promise<ReadingSources> {
  return apiGet<ReadingSources>("/v1/reading/sources");
}

export function readingTextbook(textbookId: string, offset: number, limit = 40): Promise<ReadingTextbookPage> {
  return apiGet<ReadingTextbookPage>(
    `/v1/reading/textbooks/${encodeURIComponent(textbookId)}?offset=${offset}&limit=${limit}`,
  );
}

export function readingPosition(studentId: string, kind: ReadingSourceKind, sourceId: string): Promise<{ position: ReadingPosition | null }> {
  return apiGet(`/v1/reading/position/${studentId}?source_kind=${kind}&source_id=${encodeURIComponent(sourceId)}`);
}

export function saveReadingPosition(args: {
  studentId: string; kind: ReadingSourceKind; sourceId: string;
  blockIndex: number; blockId?: string | null; totalBlocks?: number | null;
}): Promise<{ position: ReadingPosition }> {
  return apiPut("/v1/reading/position", {
    student_id: args.studentId,
    source_kind: args.kind,
    source_id: args.sourceId,
    block_index: args.blockIndex,
    block_id: args.blockId ?? null,
    total_blocks: args.totalBlocks ?? null,
  });
}

// ── Animator（POST /v1/animate）：确定性内核编排出的纯数据时间线 ──────────────
// 播放器是自托管静态脚本（/v1/edu-assets/mneme-animator-1/player.js），在
// sandbox="allow-scripts" 的 iframe 里按白名单图元画 SVG；时间线里没有任何代码。
export type AnimKind = "solid_geometry" | "conic_chord" | "equation_balance" | "function_graph";

export interface AnimFrame {
  title: string;
  caption: string;
  readout?: string;
  show: string[];
  highlight: string[];
  set: Record<string, Record<string, unknown>>;
  camera?: { azimuth: number; elevation: number };
  duration_ms: number;
}

export interface AnimSpec {
  spec_version: "mneme.anim/1";
  kind: AnimKind;
  title: string;
  answer: { label: string; latex: string };
  canvas: { mode: "2d" | "3d"; view: number[]; target?: number[] };
  shapes: Record<string, unknown>[];
  frames: AnimFrame[];
  fingerprint: string;
}

export function animate(kind: AnimKind, params: unknown): Promise<AnimSpec> {
  return eduPost<AnimSpec>("/v1/animate", { kind, params });
}

/** 自托管教学静态资源的绝对 URL 前缀（sandbox iframe 是 opaque origin，必须写绝对地址）。 */
export function eduAssetBase(): string {
  const base = API_BASE || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/v1/edu-assets`;
}
