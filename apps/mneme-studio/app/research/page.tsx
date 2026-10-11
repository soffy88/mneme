"use client";

import { useCallback, useEffect, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import {
  createResearch, getResearch, getToken, listResearch, redirectToLogin,
  type ResearchList, type ResearchPoint, type ResearchReport,
} from "@/lib/mcp";

// 研究报告：只在本地教材库里找依据，每条结论都标出 书/页；找不到依据就直说，不编造。
// 研究不影响掌握度——掌握度只由真实作答决定。

const STATUS_LABEL: Record<string, string> = {
  ready: "已完成",
  extractive: "教材摘录",
  no_sources: "没有找到教材依据",
};

const EXAMPLES = ["勾股定理的证明方法", "牛顿第二定律在生活中的例子"];

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("zh-CN", { hour12: false });
}

function errText(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  try {
    const parsed = JSON.parse(raw.replace(/^[^{]*/, "")) as { detail?: string };
    if (parsed.detail) return parsed.detail;
  } catch { /* not json */ }
  return raw;
}

function Cites({ p, onPick }: { p: ResearchPoint; onPick: (id: string) => void }) {
  return (
    <span className="ml-1 inline-flex flex-wrap gap-1 align-middle">
      {p.citations.map((c) => (
        <button
          key={c.source_id}
          type="button"
          onClick={() => onPick(c.source_id)}
          className="rounded border px-1 text-xs text-[var(--o-color-fg-muted,#666)] hover:bg-black/5"
          title={`chunk ${c.chunk_id}`}
        >
          {c.source_id} 《{c.book_name ?? "教材"}》{c.page_number != null ? ` 第${c.page_number}页` : ""}
        </button>
      ))}
    </span>
  );
}

export default function ResearchPage() {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ResearchReport | null>(null);
  const [history, setHistory] = useState<ResearchList | null>(null);
  const [openSource, setOpenSource] = useState<string | null>(null);

  const loadHistory = useCallback(async () => {
    try { setHistory(await listResearch()); } catch (e) { setError(errText(e)); }
  }, []);

  useEffect(() => {
    if (!getToken()) { redirectToLogin(); return; }
    void loadHistory();
  }, [loadHistory]);

  const submit = useCallback(async (q: string) => {
    const text = q.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    setOpenSource(null);
    try {
      setReport(await createResearch(text));
      await loadHistory();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy(false);
    }
  }, [loadHistory]);

  const open = useCallback(async (id: string) => {
    setError(null);
    setOpenSource(null);
    try { setReport(await getResearch(id)); } catch (e) { setError(errText(e)); }
  }, []);

  const r = report?.report;
  const remaining = history ? Math.max(0, history.daily_limit - history.used_today) : null;

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="research-root">
      <h1 className="text-2xl font-bold">研究报告</h1>
      <ProductNav />
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        提一个学习问题，Mneme 只在你的教材里找答案，每条结论后面都会标出是哪本书第几页。
        教材里找不到依据的内容，它会直接告诉你，不会乱编。
      </p>

      <OCard>
        <div className="p-4 space-y-3">
          <textarea
            className="w-full min-h-[80px] rounded-lg border p-3"
            placeholder="比如：勾股定理的证明方法"
            maxLength={200}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            data-testid="research-question"
          />
          <div className="flex flex-wrap items-center gap-2">
            <OButton onClick={() => void submit(question)} disabled={busy || !question.trim()}>
              {busy ? "正在查教材…" : "开始研究"}
            </OButton>
            {EXAMPLES.map((ex) => (
              <OButton key={ex} size="sm" variant="ghost" disabled={busy}
                onClick={() => { setQuestion(ex); void submit(ex); }}>
                {ex}
              </OButton>
            ))}
          </div>
          {remaining != null && (
            <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
              今天还可以研究 {remaining} 次（每天 {history?.daily_limit} 次）
            </div>
          )}
          {busy && <div className="text-xs">AI 正在阅读教材并整理报告，可能需要几十秒…</div>}
        </div>
      </OCard>

      {error && <OCard><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>}

      {report && r && (
        <OCard data-testid="research-report">
          <OCardHeader>
            <OCardTitle>{r.title}</OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-4">
            <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
              问题：{report.question} · {STATUS_LABEL[report.status] ?? report.status} · {when(report.created_at)}
            </div>
            {report.status === "extractive" && (
              <div className="rounded-lg border border-dashed p-2 text-xs">
                AI 讲解暂时不可用，下面是教材原文摘录（逐条标了出处）。
              </div>
            )}
            {r.summary && (
              <p className="text-sm leading-relaxed">
                {r.summary.text}<Cites p={r.summary} onPick={setOpenSource} />
              </p>
            )}
            {r.sections.map((sec, i) => (
              <div key={i} className="space-y-2">
                <div className="font-semibold">{sec.heading}</div>
                <ul className="list-disc pl-5 space-y-1 text-sm">
                  {sec.points.map((p, j) => (
                    <li key={j}>{p.text}<Cites p={p} onPick={setOpenSource} /></li>
                  ))}
                </ul>
              </div>
            ))}
            {r.unsupported.length > 0 && (
              <div className="space-y-1">
                <div className="text-sm font-semibold">没有找到依据的说法</div>
                <ul className="list-disc pl-5 text-sm text-[var(--o-color-fg-muted,#777)]">
                  {r.unsupported.map((u, i) => <li key={i}><s>{u.text}</s>（{u.note}）</li>)}
                </ul>
              </div>
            )}
            {r.gaps.length > 0 && (
              <div className="rounded-lg bg-black/5 p-3 text-sm space-y-1">
                {r.gaps.map((g, i) => <div key={i}>· {g}</div>)}
              </div>
            )}
            {report.sources.length > 0 && (
              <div className="space-y-2">
                <div className="text-sm font-semibold">教材来源</div>
                {report.sources.map((s) => (
                  <div key={s.id} className={`rounded-lg border p-2 text-xs ${openSource === s.id ? "ring-2" : ""}`}>
                    <button type="button" className="font-medium" onClick={() => setOpenSource(openSource === s.id ? null : s.id)}>
                      {s.id} 《{s.book_name ?? "教材"}》{s.page_number != null ? ` 第${s.page_number}页` : ""}
                      {s.verified ? " · 已核对" : " · 推断出处"}
                    </button>
                    {openSource === s.id && <div className="mt-1 whitespace-pre-wrap">{s.excerpt}</div>}
                  </div>
                ))}
              </div>
            )}
          </div>
        </OCard>
      )}

      {history && history.items.length === 0 && !report && (
        <OEmptyState title="还没有研究记录" description="试试上面的示例问题。" />
      )}
      {history && history.items.length > 0 && (
        <OCard>
          <OCardHeader><OCardTitle>我的研究记录</OCardTitle></OCardHeader>
          <div className="p-4 space-y-2">
            {history.items.map((it) => (
              <button key={it.id} type="button" onClick={() => void open(it.id)}
                className="block w-full rounded-lg border p-2 text-left text-sm hover:bg-black/5">
                <div className="font-medium">{it.title ?? it.question}</div>
                <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                  {it.question} · {STATUS_LABEL[it.status] ?? it.status} · {when(it.created_at)}
                </div>
              </button>
            ))}
          </div>
        </OCard>
      )}
    </main>
  );
}
