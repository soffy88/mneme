"use client";

import { useCallback, useEffect, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import {
  getStudentId, getToken, mcp, redirectToLogin,
  type MemoryInspectView, type MemoryLayer, type MemoryEvidenceItem,
} from "@/lib/mcp";

// 我的记忆：学生本人查看 Mneme 记住了什么（对话流水 / 沉淀摘要 / 有证据的判断），
// 并可让 Mneme 忘掉其中任意一条。只读 + 本人删除；掌握度不受影响（记忆不进门控）。

const KIND_LABEL: Record<string, string> = {
  tutor_turn: "辅导对话", chat_turn: "对话", lesson: "学习", review: "复习",
};

function preview(content: unknown): string {
  if (content == null) return "";
  if (typeof content === "string") return content;
  if (typeof content === "object") {
    const o = content as Record<string, unknown>;
    for (const k of ["summary", "text", "note", "message", "content", "question", "n"]) {
      if (typeof o[k] === "string") return o[k] as string;
    }
    return JSON.stringify(content);
  }
  return String(content);
}

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("zh-CN", { hour12: false });
}

export default function MemoryInspectPage() {
  const [sid, setSid] = useState("");
  const [view, setView] = useState<MemoryInspectView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<Record<string, MemoryEvidenceItem[] | "loading">>({});

  const load = useCallback(async (studentId: string) => {
    try {
      setView(await mcp.memoryInspect(studentId));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    const s = getStudentId()!;
    setSid(s);
    void load(s);
  }, [load]);

  const forget = useCallback(async (layer: MemoryLayer, id: string) => {
    setBusy(id);
    try {
      await mcp.memoryForget(sid, layer, id);
      setConfirming(null);
      await load(sid);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, [sid, load]);

  const toggleEvidence = useCallback(async (claimId: string) => {
    if (evidence[claimId]) {
      setEvidence((m) => { const n = { ...m }; delete n[claimId]; return n; });
      return;
    }
    setEvidence((m) => ({ ...m, [claimId]: "loading" }));
    try {
      const r = await mcp.memoryEvidence(claimId);
      setEvidence((m) => ({ ...m, [claimId]: r.evidence }));
    } catch {
      setEvidence((m) => ({ ...m, [claimId]: [] }));
    }
  }, [evidence]);

  const ForgetControl = ({ layer, id }: { layer: MemoryLayer; id: string }) =>
    confirming === id ? (
      <span className="flex items-center gap-2 text-xs">
        <span>确定让 Mneme 忘掉这条？</span>
        <OButton size="sm" variant="destructive" disabled={busy === id} onClick={() => void forget(layer, id)} data-testid="forget-confirm">
          {busy === id ? "删除中…" : "忘掉"}
        </OButton>
        <OButton size="sm" variant="ghost" onClick={() => setConfirming(null)}>取消</OButton>
      </span>
    ) : (
      <OButton size="sm" variant="outline" onClick={() => setConfirming(id)} data-testid="forget">忘掉这条</OButton>
    );

  const total = view ? view.episodic.length + view.semantic.length + view.claims.length : 0;

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="memory-inspect-root">
      <h1 className="text-2xl font-bold">我的记忆</h1>
      <ProductNav />
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        这里是 Mneme 记住的关于你的全部内容。只有你自己能看到；你可以让它忘掉任何一条。
        忘掉记忆不会改变你的掌握度——掌握度只由你的真实作答决定。
      </p>

      {error && <OCard><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>}

      {view && total === 0 && (
        <OEmptyState title="还没有记忆" description="和 Mneme 学习、对话之后，它记住的内容会出现在这里。" />
      )}

      {view && view.claims.length > 0 && (
        <OCard data-testid="claims">
          <OCardHeader><OCardTitle>Mneme 对你的判断（有证据）</OCardTitle></OCardHeader>
          <div className="p-4 space-y-3">
            {view.claims.map((c) => (
              <div key={c.id} className="rounded-lg border p-3 space-y-2">
                <div className="font-medium">{c.claim_text}</div>
                <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                  {c.knowledge_ref ?? c.subject_id} · 证据 {c.evidence_count} 条 · {when(c.created_at)}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <OButton size="sm" variant="ghost" onClick={() => void toggleEvidence(c.id)}>
                    {evidence[c.id] ? "收起证据" : "为什么这样认为？"}
                  </OButton>
                  <ForgetControl layer="claim" id={c.id} />
                </div>
                {evidence[c.id] === "loading" && <div className="text-xs">加载证据…</div>}
                {Array.isArray(evidence[c.id]) && (
                  <ul className="text-xs space-y-1 pl-4 list-disc">
                    {(evidence[c.id] as MemoryEvidenceItem[]).length === 0
                      ? <li>暂无可展示的证据</li>
                      : (evidence[c.id] as MemoryEvidenceItem[]).map((e) => (
                        <li key={e.id}>{e.evidence_type}{e.knowledge_ref ? ` · ${e.knowledge_ref}` : ""} · {when(e.occurred_at)}{e.source ? ` · 来源 ${e.source}` : ""}</li>
                      ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        </OCard>
      )}

      {view && view.semantic.length > 0 && (
        <OCard data-testid="semantic">
          <OCardHeader><OCardTitle>沉淀的摘要</OCardTitle></OCardHeader>
          <div className="p-4 space-y-3">
            {view.semantic.map((s) => (
              <div key={s.id} className="rounded-lg border p-3 space-y-2">
                <div className="text-sm font-semibold">{s.topic}</div>
                <div className="text-sm whitespace-pre-wrap">{preview(s.content)}</div>
                <div className="flex items-center justify-between text-xs text-[var(--o-color-fg-muted,#888)]">
                  <span>由 {s.merged_from_count} 条记录汇总 · {when(s.updated_at)}</span>
                  <ForgetControl layer="semantic" id={s.id} />
                </div>
              </div>
            ))}
          </div>
        </OCard>
      )}

      {view && view.episodic.length > 0 && (
        <OCard data-testid="episodic">
          <OCardHeader><OCardTitle>最近的学习记录</OCardTitle></OCardHeader>
          <div className="p-4 space-y-3">
            {view.episodic.map((e) => (
              <div key={e.id} className="rounded-lg border p-3 space-y-2">
                <div className="text-xs text-[var(--o-color-fg-muted,#888)]">{KIND_LABEL[e.kind] ?? e.kind} · {when(e.created_at)}</div>
                <div className="text-sm whitespace-pre-wrap line-clamp-4">{preview(e.content)}</div>
                <div className="flex justify-end"><ForgetControl layer="episodic" id={e.id} /></div>
              </div>
            ))}
          </div>
        </OCard>
      )}
    </main>
  );
}
