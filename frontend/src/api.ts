const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000"

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
  const res = await req<{ access_token: string }>("/v1/auth/login", {
    method: "POST",
    body: JSON.stringify({ phone, code }),
  })
  setToken(res.access_token)
  return res
}

export async function getMe() {
  return req<{ id: string; phone: string; role: string; name: string }>("/v1/auth/me")
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
