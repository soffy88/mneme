// 默认同源（生产由 api 容器同域服务）；本地开发用 .env.development 指向 :8000
const BASE = import.meta.env.VITE_API_BASE ?? ""

function token(): string | null {
  return localStorage.getItem("mneme_token")
}

async function req<T>(path: string, opts: RequestInit = {}): Promise<T> {
  const tok = token()
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(opts.headers as Record<string, string> ?? {}),
  }
  if (tok) headers["Authorization"] = `Bearer ${tok}`
  const r = await fetch(BASE + path, { ...opts, headers })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export function setToken(t: string) { localStorage.setItem("mneme_token", t) }
export function clearToken() { localStorage.removeItem("mneme_token") }

export async function login(phone: string, code: string) {
  // 后端返回 {token, user}（非 access_token）
  const res = await req<{ token: string; user: { id: string; name: string } }>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  })
  setToken(res.token)
  return res
}

export async function registerStudent(
  phone: string, code: string, name: string,
  opts: { birth_date?: string; grade?: string } = {},
) {
  const res = await req<{ token: string; user: { id: string; name: string; invite_code?: string } }>(
    "/v1/auth/register/student",
    {
      method: "POST",
      body: JSON.stringify({
        phone, code, name,
        birth_date: opts.birth_date ?? "2008-01-01",  // 默认 ≥14，免监护人同意
        grade: opts.grade ?? "高一",
      }),
    },
  )
  setToken(res.token)
  return res
}

export async function getMe() {
  return req<{ id: string; phone: string; role: string; name: string }>("/v1/auth/me")
}

// ===== 英语 =====
export interface EssayGuideResult {
  rubric_scores: Record<string, unknown> | string | null
  guidance_questions: string[]
  is_completed: boolean
}
export async function essayGuide(essayText: string, grade: string, essayType: string) {
  return req<EssayGuideResult>("/v1/essay/guide", {
    method: "POST",
    body: JSON.stringify({ essay_text: essayText, grade, essay_type: essayType }),
  })
}

export interface KU {
  id: string
  name: string
  description: string | null
  textbook_id: string
  textbook_file_id: string | null
  cluster_id: string
  cluster_name: string
  cluster_order: number
  subject: string
  grade: string
  book_name: string
  ku_type: string
  difficulty: number
  prerequisites: string[]
  exam_frequency: string
  p_mastery: number | null
  mastery_color: string | null
  rich_content?: Record<string, string | string[]> | null
  prereq_mastery?: { ku_id: string; name?: string; p_mastery: number | null }[]
}

export async function listKUs(subject: string, student_id?: string): Promise<KU[]> {
  const qs = new URLSearchParams({ subject })
  if (student_id) qs.set("student_id", student_id)
  return req<KU[]>(`/v1/knowledge-points?${qs}`)
}

export async function getKU(ku_id: string, student_id?: string): Promise<KU> {
  const qs = student_id ? `?student_id=${student_id}` : ""
  return req<KU>(`/v1/knowledge-points/${ku_id}${qs}`)
}

export function pdfUrl(file_id: string): string {
  return `${BASE}/v1/textbook-files/${file_id}/content?token=${token()}`
}

function _payload(): { sub?: string; role?: string } | null {
  try {
    const tok = token()
    if (!tok) return null
    return JSON.parse(atob(tok.split(".")[1]))
  } catch { return null }
}

/** 从 JWT 解出 student_id（payload.sub）。无 token 或解析失败返回 undefined。 */
export function currentStudentId(): string | undefined {
  return _payload()?.sub
}

/** 当前用户角色（student / parent）。 */
export function currentRole(): string | undefined {
  return _payload()?.role
}

// ── 家长端 ────────────────────────────────────────────────────────
export async function registerParent(phone: string, code: string, name: string, inviteCode: string) {
  const res = await req<{ token: string; user: { id: string; name: string } }>("/v1/auth/register/parent", {
    method: "POST",
    body: JSON.stringify({ phone, code, name, invite_code: inviteCode }),
  })
  setToken(res.token)
  return res
}

export interface Child {
  student_id: string
  name: string | null
  grade: string | null
}

export async function getParentChildren(): Promise<Child[]> {
  return req<Child[]>("/v1/parent/children")
}

export interface ParentOverview {
  weak_kc_count: number
  total_kc_practiced: number
  streak: { current_streak: number; longest_streak: number }
  recent_sessions: number
}

export async function getParentOverview(studentId: string): Promise<ParentOverview> {
  return req<ParentOverview>(`/v1/parent/overview/${studentId}`)
}

export interface ParentAlert {
  id: string
  type: string | null
  level: string | null
  content: string | null
  is_read: boolean
  created_at: string | null
}

export async function getAlerts(studentId: string, parentId: string): Promise<ParentAlert[]> {
  return req<ParentAlert[]>(`/v1/parent/alerts/${studentId}?parent_id=${parentId}`)
}

export async function runAlertChecks(studentId: string, parentId: string): Promise<{
  checked: number
  alerts: { type: string; level: string; content: string }[]
}> {
  return req(`/v1/parent/alerts/${studentId}/check?parent_id=${parentId}`, { method: "POST" })
}

export interface DailyReport {
  date: string
  report_text: string
  n_interactions: number
  current_streak: number
  weak_kc_count: number
}

export async function getParentReport(studentId: string): Promise<DailyReport> {
  return req<DailyReport>(`/v1/parent/report/${studentId}`)
}

// ── 认知状态：掌握度总览 / 成长曲线 ───────────────────────────────
export interface MasteryItem {
  kc_id: string
  p_mastery: number | null
  long_term_mastery: number | null
  effective_mastery: number
  error_type?: string | null
  n_attempts?: number
  peer_percentile?: number | null
}

export async function getMasteryOverview(studentId: string): Promise<MasteryItem[]> {
  return req<MasteryItem[]>(`/v1/mastery/${studentId}`)
}

export interface CurvePoint {
  month: string
  long_term_mastery: number | null
  dominant_error_type: string | null
}

export async function getMasteryCurve(studentId: string, kcId: string): Promise<CurvePoint[]> {
  return req<CurvePoint[]>(`/v1/mastery/curve/${studentId}/${encodeURIComponent(kcId)}`)
}

// ── 今日计划 ──────────────────────────────────────────────────────
export interface DailyTask {
  type: string
  title: string
  subject: string
  ku_ids: string[]
  priority: number
  reason: string
  estimated_minutes: number
}
export interface DailyPlan {
  date: string
  exam_countdown_days: number | null
  subjects_summary: { subject: string; task_count: number; estimated_minutes: number }[]
  tasks: DailyTask[]
}

export async function getDailyPlan(studentId: string, subject?: string): Promise<DailyPlan> {
  const qs = subject ? `?subject=${encodeURIComponent(subject)}` : ""
  return req<DailyPlan>(`/v1/daily-plan/${studentId}${qs}`)
}

// ── 留存：连续天数 + 本周成长摘要 ─────────────────────────────────
export interface WeeklyDigest {
  current_streak: number
  active_today: boolean
  n_interactions_7d: number
  distinct_kcs_7d: number
  accuracy_7d: number | null
  days_active_7d: number
  effort_gains_7d: number
  headline: string
}

export async function getWeeklyDigest(studentId: string): Promise<WeeklyDigest> {
  return req<WeeklyDigest>(`/v1/weekly-digest/${studentId}`)
}

// ── JOL 自测校准（先预测把握，再看实际对错） ─────────────────────
export async function postInteraction(p: {
  student_id: string
  kc_id: string
  is_correct: boolean
  predicted_confidence?: number
  source?: string
  struggled?: boolean
  effortless?: boolean
  used_answer?: boolean
  time_spent_seconds?: number
}) {
  return req("/v1/interaction", {
    method: "POST",
    body: JSON.stringify({ source: "quick", ...p }),
  })
}

// ── 错题/到期复习（检索练习：先自评再揭示，看答案=Again） ──────────
export interface DueReviewItem {
  kc_id: string
  variant_question: string
  variant_answer: string
  due_since: string | null
  fsrs_interval: number
}

export async function getDueReview(studentId: string): Promise<DueReviewItem[]> {
  return req<DueReviewItem[]>(`/v1/review/due/${studentId}`)
}

// ── 交错复习池（M-B：相邻题 KC 不同） ─────────────────────────────
export interface ReviewQueueItem {
  kc_id: string
  due: string
}

export async function getReviewQueue(studentId: string): Promise<ReviewQueueItem[]> {
  return req<ReviewQueueItem[]>(`/v1/review-queue/${studentId}`)
}

export interface Calibration {
  n: number
  brier: number | null
  mean_predicted: number | null
  accuracy: number | null
  overconfidence: number | null
}

export async function getCalibration(studentId: string): Promise<Calibration> {
  return req<Calibration>(`/v1/calibration/${studentId}`)
}

// ── 前置图谱归因（先补根再补叶） ──────────────────────────────────
export interface WeakPrereq {
  ku_id: string
  name: string
  p_mastery: number | null
  status: "weak" | "unpracticed"
}
export interface WeakRoot {
  ku_id: string
  name: string
  p_mastery: number
  weak_prerequisites: WeakPrereq[]
}

export async function getWeakRoots(studentId: string): Promise<WeakRoot[]> {
  const r = await req<{ roots: WeakRoot[] }>(`/v1/weak-roots/${studentId}`)
  return r.roots
}

// ── 努力收益看板（M-F） ───────────────────────────────────────────
export interface EffortGain {
  question_id: string | null
  kc: string | null
  struggle_score: number
  retention_delta: number
  effortful_gain: number
  occurred_at: string | null
}

export async function getEffortfulGains(studentId: string, limit = 10): Promise<EffortGain[]> {
  const r = await req<{ top_gains: EffortGain[] }>(`/v1/effortful-gains/${studentId}?limit=${limit}`)
  return r.top_gains
}

// ── 苏格拉底引导（基于知识点） ────────────────────────────────────
export interface SocraticStart {
  session_id: string
  mode: string
  first_question: string
}

export async function startSocraticForKu(kuId: string, studentId: string): Promise<SocraticStart> {
  return req<SocraticStart>("/v1/socratic/start-for-ku", {
    method: "POST",
    body: JSON.stringify({ ku_id: kuId, student_id: studentId }),
  })
}

/** SSE 流式回复。onDelta 逐段回调，onDone 结束。返回 Promise 在流结束时 resolve。 */
export async function sendSocraticMessage(
  sessionId: string,
  text: string,
  onDelta: (s: string) => void,
  onDone?: (turn: number) => void,
): Promise<void> {
  const tok = token()
  const headers: Record<string, string> = {}
  if (tok) headers["Authorization"] = `Bearer ${tok}`
  const url = `${BASE}/v1/socratic/${sessionId}/message?student_message=${encodeURIComponent(text)}`
  const r = await fetch(url, { method: "POST", headers })
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)
  const reader = r.body.getReader()
  const decoder = new TextDecoder()
  let buf = ""
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split("\n\n")
    buf = parts.pop() ?? ""
    for (const part of parts) {
      const line = part.trim()
      if (!line.startsWith("data:")) continue
      try {
        const evt = JSON.parse(line.slice(5).trim())
        if (evt.delta) onDelta(evt.delta as string)
        else if (evt.done) onDone?.(evt.turn as number)
        else if (evt.error) throw new Error(evt.error as string)
      } catch { /* 跳过半包/坏帧 */ }
    }
  }
}

// ── 试卷上传（冷启动钩子） ────────────────────────────────────────
export interface PaperFindings {
  paper_id: string
  total_questions: number
  correct_count: number
  wrong_count: number
  wrong_questions: { kc_ids?: string[]; error_type?: string | null; [k: string]: unknown }[]
}

export async function uploadPaper(studentId: string, file: File): Promise<PaperFindings> {
  const tok = token()
  const headers: Record<string, string> = {}
  if (tok) headers["Authorization"] = `Bearer ${tok}`
  const fd = new FormData()
  fd.append("file", file)
  const r = await fetch(`${BASE}/v1/papers/upload?student_id=${studentId}`, {
    method: "POST", headers, body: fd, // 不设 Content-Type，交给浏览器带 multipart boundary
  })
  if (!r.ok) {
    const err = await r.json().catch(() => ({}))
    throw new Error(err.detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

// ── 错题本（检索约束：先自评再揭示） ──────────────────────────────
export interface ErrorJournalItem {
  question_id: string
  kc_id: string
  error_tag: string
  wrong_at: string
  can_practice_variant: boolean
}

export async function getErrorJournal(studentId: string): Promise<{ distribution: unknown; items: ErrorJournalItem[] }> {
  return req(`/v1/error-journal/${studentId}`)
}

export async function escapeSocratic(sessionId: string): Promise<{ outline: string[]; note: string }> {
  return req(`/v1/socratic/${sessionId}/escape`, { method: "POST" })
}

export async function endSocratic(sessionId: string, outcome = "partial") {
  return req<{ session_id: string; outcome: string; duration_seconds: number }>(
    `/v1/socratic/${sessionId}/end?outcome=${encodeURIComponent(outcome)}`,
    { method: "POST" },
  )
}
