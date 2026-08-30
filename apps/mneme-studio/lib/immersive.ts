// Immersive Learning API client — /v2/immersive/*
// Reuses mneme auth session (mneme_token / mneme_user); never invents mastery locally.

import { getToken, redirectToLogin, McpError } from "@/lib/mcp";

const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000").replace(
  /\/$/,
  ""
);

export const IMMERSIVE_MOCK =
  process.env.NODE_ENV !== "production" &&
  (process.env.NEXT_PUBLIC_IMMERSIVE_MOCK === "1" ||
    process.env.NEXT_PUBLIC_IMMERSIVE_MOCK === "true");

export interface ImmersiveSegment {
  segment_id: string;
  order_index: number;
  start_ms: number;
  end_ms: number;
  text: string;
  translated_text?: string | null;
  speaker?: string | null;
  language?: string | null;
}

export interface ImmersiveMediaItem {
  media_id: string;
  title: string | null;
  media_type: string;
  language?: string | null;
  duration_ms?: number | null;
  content_provenance?: unknown;
  processing_state?: string | null;
  created_at?: string | null;
}

export interface ImmersiveMediaDetail extends ImmersiveMediaItem {
  playback_url?: string | null;
  has_storage?: boolean;
}

export interface ImmersiveSession {
  session_id: string;
  media_id: string;
  playhead_ms: number;
  current_segment_id: string | null;
  scaffold_level: number;
  state: string;
  note?: string;
}

export interface PracticeScore {
  correctness: boolean;
  partial_credit: number;
  edit_distance?: number;
  normalized_expected?: string;
  normalized_submitted?: string;
  verifier?: string;
  verifier_version?: string;
}

export interface PracticeResult {
  score: PracticeScore;
  ingest?: unknown;
  segment_text?: string;
}

async function immersiveFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    if (res.status === 401 && typeof window !== "undefined") redirectToLogin();
    throw new McpError(res.status, await res.text());
  }
  return (await res.json()) as T;
}

export const immersiveApi = {
  status: () =>
    immersiveFetch<{ enabled: boolean; feature_gate_reason: string }>(
      "/v2/immersive/status"
    ),

  listMedia: (studentId: string) =>
    immersiveFetch<{ items: ImmersiveMediaItem[] }>(
      `/v2/immersive/${studentId}/media`
    ),

  getMedia: (studentId: string, mediaId: string) =>
    immersiveFetch<ImmersiveMediaDetail>(
      `/v2/immersive/${studentId}/media/${mediaId}`
    ),

  listSegmentsPage: (
    studentId: string,
    mediaId: string,
    offset = 0,
    limit = 500
  ) =>
    immersiveFetch<{
      items: ImmersiveSegment[];
      total: number;
      offset: number;
      limit: number;
      transcript_id?: string;
    }>(
      `/v2/immersive/${studentId}/media/${mediaId}/segments?offset=${offset}&limit=${limit}`
    ),

  /** Fetch all segments (API page size ≤500). */
  async listAllSegments(
    studentId: string,
    mediaId: string
  ): Promise<ImmersiveSegment[]> {
    const pageSize = 500;
    const first = await immersiveApi.listSegmentsPage(
      studentId,
      mediaId,
      0,
      pageSize
    );
    const items = [...first.items];
    while (items.length < first.total) {
      const page = await immersiveApi.listSegmentsPage(
        studentId,
        mediaId,
        items.length,
        pageSize
      );
      if (page.items.length === 0) break;
      items.push(...page.items);
    }
    return items;
  },

  openSession: (studentId: string, mediaId: string) =>
    immersiveFetch<ImmersiveSession>(
      `/v2/immersive/${studentId}/media/${mediaId}/session`,
      { method: "POST", body: "{}" }
    ),

  patchSession: (
    studentId: string,
    sessionId: string,
    body: {
      playhead_ms?: number;
      current_segment_id?: string | null;
      scaffold_level?: number;
      state?: string;
    }
  ) =>
    immersiveFetch<{
      session_id: string;
      playhead_ms: number;
      current_segment_id: string | null;
      scaffold_level: number;
      state: string;
    }>(`/v2/immersive/${studentId}/sessions/${sessionId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),

  practiceDictation: (
    studentId: string,
    body: {
      media_id: string;
      segment_id: string;
      submitted: string;
      session_id?: string | null;
      scaffold_level?: number;
    }
  ) =>
    immersiveFetch<PracticeResult>(
      `/v2/immersive/${studentId}/practice/dictation`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  practiceListening: (
    studentId: string,
    body: {
      media_id: string;
      segment_id: string;
      submitted_meaning: string;
      session_id?: string | null;
      scaffold_level?: number;
    }
  ) =>
    immersiveFetch<PracticeResult>(
      `/v2/immersive/${studentId}/practice/listening`,
      { method: "POST", body: JSON.stringify(body) }
    ),

  practiceComprehension: (
    studentId: string,
    body: {
      media_id: string;
      segment_id: string;
      expected_option_id: string;
      submitted_option_id: string;
      session_id?: string | null;
      scaffold_level?: number;
      question_provenance?: Record<string, unknown>;
    }
  ) =>
    immersiveFetch<PracticeResult>(
      `/v2/immersive/${studentId}/practice/comprehension`,
      { method: "POST", body: JSON.stringify(body) }
    ),
};

/** In-memory fake cues for virtualization tests (no backend). */
export function generateMockSegments(count = 10_000): ImmersiveSegment[] {
  const out: ImmersiveSegment[] = [];
  const duration = 3000;
  for (let i = 0; i < count; i++) {
    const start = i * duration;
    out.push({
      segment_id: `mock-seg-${i}`,
      order_index: i,
      start_ms: start,
      end_ms: start + duration - 50,
      text: `Mock sentence ${i + 1}. The quick brown fox jumps over the lazy dog.`,
      translated_text: `模拟句子 ${i + 1}。那只敏捷的棕色狐狸跳过了懒狗。`,
      speaker: i % 2 === 0 ? "A" : "B",
      language: "en",
    });
  }
  return out;
}

export const MOCK_MEDIA_ID = "00000000-0000-4000-8000-000000000001";
export const MOCK_SESSION_ID = "00000000-0000-4000-8000-000000000002";
