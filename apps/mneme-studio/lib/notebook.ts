// notebook / cowriter —— 学习者笔记本 + 写作教练的数据通道（/v1/notebooks、/v1/cowriter）。
//
// 同 lib/mcp.ts 的口径：同源相对路径（NEXT_PUBLIC_API_BASE=""），一套登录（mneme_token），
// 401 回 mneme-web 登录。笔记与写作建议只是学习者自己的整理，不进掌握度/门控。

import { getToken, redirectToLogin, McpError } from "@/lib/mcp";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(/\/$/, "");

async function req<T>(method: string, path: string, payload?: unknown): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      ...(payload !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: payload !== undefined ? JSON.stringify(payload) : undefined,
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

/** 从后端错误里取给人看的一句话（detail 可能是字符串或 {code,message}）。 */
export function errorMessage(e: unknown): string {
  if (e instanceof McpError) {
    try {
      const body = JSON.parse(e.detail) as { detail?: unknown };
      const d = body.detail;
      if (typeof d === "string") return d;
      if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
    } catch {
      /* fallthrough */
    }
    return e.detail || e.message;
  }
  return e instanceof Error ? e.message : String(e);
}

export function errorCode(e: unknown): string | null {
  if (e instanceof McpError) {
    try {
      const body = JSON.parse(e.detail) as { detail?: { code?: string } };
      return body.detail?.code ?? null;
    } catch {
      return null;
    }
  }
  return null;
}

// ── Notebook ────────────────────────────────────────────────────────────────

export type NotebookSourceType =
  | "chat"
  | "book_block"
  | "solve"
  | "visualize"
  | "research"
  | "cowriter"
  | "free_text";

export const SOURCE_LABEL: Record<NotebookSourceType, string> = {
  chat: "对话回答",
  book_block: "活书内容",
  solve: "解题结果",
  visualize: "可视化",
  research: "研究报告",
  cowriter: "写作草稿",
  free_text: "随手记",
};

export interface NotebookSummary {
  id: string;
  name: string;
  description: string | null;
  created_at: string | null;
  updated_at: string | null;
  record_count?: number;
}

export interface NotebookRecord {
  id: string;
  notebook_id: string;
  source_type: NotebookSourceType;
  source_id: string | null;
  kc_id: string | null;
  title: string | null;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
}

export interface NotebookDetail extends NotebookSummary {
  records: NotebookRecord[];
}

export interface NewRecord {
  source_type: NotebookSourceType;
  content: string;
  source_id?: string | null;
  kc_id?: string | null;
  title?: string | null;
  metadata?: Record<string, unknown>;
}

export const notebooks = {
  list: () => req<{ notebooks: NotebookSummary[] }>("GET", "/v1/notebooks"),
  create: (name: string, description?: string) =>
    req<NotebookSummary>("POST", "/v1/notebooks", { name, description }),
  get: (id: string) => req<NotebookDetail>("GET", `/v1/notebooks/${encodeURIComponent(id)}`),
  rename: (id: string, name: string) =>
    req<NotebookSummary>("PATCH", `/v1/notebooks/${encodeURIComponent(id)}`, { name }),
  remove: (id: string) => req<{ deleted: string }>("DELETE", `/v1/notebooks/${encodeURIComponent(id)}`),
  addRecord: (id: string, rec: NewRecord) =>
    req<NotebookRecord>("POST", `/v1/notebooks/${encodeURIComponent(id)}/records`, rec),
  updateRecord: (id: string, rid: string, patch: { title?: string; content?: string }) =>
    req<NotebookRecord>(
      "PATCH",
      `/v1/notebooks/${encodeURIComponent(id)}/records/${encodeURIComponent(rid)}`,
      patch
    ),
  removeRecord: (id: string, rid: string) =>
    req<{ deleted: string }>(
      "DELETE",
      `/v1/notebooks/${encodeURIComponent(id)}/records/${encodeURIComponent(rid)}`
    ),
  save: (rec: NewRecord & { notebook_id?: string | null; notebook_name?: string | null }) =>
    req<{ notebook_id: string; record: NotebookRecord }>("POST", "/v1/notebooks/save", rec),
};

// ── Co-Writer ───────────────────────────────────────────────────────────────

export type CowriterAction = "rewrite" | "expand" | "shorten" | "grammar" | "outline";

export const ACTION_LABEL: Record<CowriterAction, string> = {
  rewrite: "改写",
  expand: "扩写",
  shorten: "缩写",
  grammar: "语法/错字",
  outline: "提纲",
};

export interface CowriterHunk {
  id: string;
  op: "replace" | "insert" | "delete";
  start: number;
  end: number;
  before: string;
  after: string;
}

export type CowriterSegment = { type: "equal"; text: string } | { type: "hunk"; hunk_id: string };

export interface CowriterCitation {
  id: string;
  title: string;
  highlight: string;
  source: string;
  verified: boolean;
}

export interface CowriterSuggestion {
  action: CowriterAction;
  language: "zh" | "en";
  original: string;
  suggestion: string;
  notes: string[];
  hunks: CowriterHunk[];
  segments: CowriterSegment[];
  truncated: boolean;
  length_cap: number;
  citations: CowriterCitation[];
  usage: { used_today: number; daily_limit: number; is_admin: boolean };
}

export interface CowriterLimits {
  used_today: number;
  daily_limit: number;
  is_admin: boolean;
  min_input_units: number;
}

export const cowriter = {
  limits: () => req<CowriterLimits>("GET", "/v1/cowriter/limits"),
  suggest: (body: { action: CowriterAction; text: string; instruction?: string; cite?: boolean }) =>
    req<CowriterSuggestion>("POST", "/v1/cowriter/suggest", body),
};

/** 把被接受的 hunks 应用到原文（与 services/cowriter_service.apply_hunks 同一算法）。 */
export function applyHunks(original: string, hunks: CowriterHunk[], accepted: Set<string>): string {
  const sorted = [...hunks].sort((a, b) => a.start - b.start || a.end - b.end);
  let out = "";
  let pos = 0;
  for (const h of sorted) {
    out += original.slice(pos, h.start);
    out += accepted.has(h.id) ? h.after : h.before;
    pos = h.end;
  }
  return out + original.slice(pos);
}
