"use client";

// /studio/cowriter —— 写作教练（DeepTutor Co-Writer 对标，不代写）。
//
// 学习者自己写；选「改写/扩写/缩写/语法/提纲」后，助手只在学习者自己的文字上给修改
// 建议，以 diff 块呈现，逐块接受或拒绝，再「应用到我的文字」。不会从零替你写作文：
// 代写请求、只贴题目、文字太短都会被拒并给出引导。可选附教材引用（Knowledge Hub）。
// 草稿可存到笔记本（source_type=cowriter）。

import { useEffect, useMemo, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OInput, OBadge } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { SaveToNotebook } from "@/components/SaveToNotebook";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  cowriter,
  notebooks,
  applyHunks,
  errorMessage,
  errorCode,
  ACTION_LABEL,
  type CowriterAction,
  type CowriterSuggestion,
  type CowriterLimits,
} from "@/lib/notebook";

const ACTIONS: CowriterAction[] = ["grammar", "rewrite", "expand", "shorten", "outline"];
const DRAFT_KEY = "mneme_cowriter_draft";

export default function CowriterPage() {
  const [text, setText] = useState("");
  const [instruction, setInstruction] = useState("");
  const [cite, setCite] = useState(false);
  const [loading, setLoading] = useState<CowriterAction | null>(null);
  const [result, setResult] = useState<CowriterSuggestion | null>(null);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [refusal, setRefusal] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limits, setLimits] = useState<CowriterLimits | null>(null);

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    const params = new URLSearchParams(window.location.search);
    const from = params.get("from");
    const nb = params.get("nb");
    void (async () => {
      try {
        setLimits(await cowriter.limits());
      } catch {
        /* limits 只是提示 */
      }
      if (from && nb) {
        try {
          const detail = await notebooks.get(nb);
          const rec = detail.records.find((r) => r.id === from);
          if (rec) setText(rec.content);
        } catch (e) {
          setError(errorMessage(e));
        }
      } else {
        const saved = localStorage.getItem(DRAFT_KEY);
        if (saved) setText(saved);
      }
    })();
  }, []);

  useEffect(() => {
    if (typeof window !== "undefined") localStorage.setItem(DRAFT_KEY, text);
  }, [text]);

  async function run(action: CowriterAction) {
    if (!text.trim() || loading) return;
    setLoading(action);
    setError(null);
    setRefusal(null);
    setResult(null);
    try {
      const r = await cowriter.suggest({
        action,
        text,
        instruction: instruction.trim() || undefined,
        cite,
      });
      setResult(r);
      setAccepted(new Set(r.hunks.map((h) => h.id)));
      setLimits((l) => (l ? { ...l, used_today: r.usage.used_today } : l));
    } catch (e) {
      const code = errorCode(e);
      if (code === "ghostwriting" || code === "prompt_only" || code === "too_short") {
        setRefusal(errorMessage(e));
      } else {
        setError(errorMessage(e));
      }
    } finally {
      setLoading(null);
    }
  }

  const preview = useMemo(
    () => (result ? applyHunks(result.original, result.hunks, accepted) : ""),
    [result, accepted]
  );

  function toggle(id: string) {
    setAccepted((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function applyToText() {
    if (!result) return;
    // 只在原文未被改动时应用（防止把建议套到已经改过的新文字上）
    if (text.trim() !== result.original) {
      setError("你在拿到建议后又改了文字，请重新获取建议。");
      return;
    }
    setText(preview);
    setResult(null);
  }

  const hunkById = useMemo(() => new Map((result?.hunks ?? []).map((h) => [h.id, h])), [result]);

  return (
    <main className="mx-auto max-w-3xl p-6 space-y-4" data-testid="cowriter-root">
      <ProductNav />
      <h1 className="text-2xl font-bold">写作助手</h1>
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        你来写，我来帮你改：语文作文、英语写作都可以。我不会替你写整篇作文，只在你自己的文字上提修改建议，每一处改不改由你决定。
      </p>

      <OCard>
        <div className="p-4 space-y-3">
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={10}
            maxLength={4000}
            placeholder="在这里写下你的作文（先自己写几句，再让我帮你改）…"
            className="w-full rounded border p-3 text-sm leading-relaxed bg-transparent"
            data-testid="cowriter-text"
          />
          <div className="flex items-center justify-between text-xs text-[var(--o-color-fg-muted,#888)]">
            <span>{text.length} / 4000</span>
            {limits && !limits.is_admin && (
              <span>
                今天已用 {limits.used_today} / {limits.daily_limit} 次
              </span>
            )}
          </div>
          <OInput
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            placeholder="补充说明（可选），例如：让结尾更有感情"
            maxLength={200}
          />
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={cite} onChange={(e) => setCite(e.target.checked)} />
            附上教材里的相关段落（可选）
          </label>
          <div className="flex flex-wrap gap-2">
            {ACTIONS.map((a) => (
              <OButton
                key={a}
                size="sm"
                onClick={() => run(a)}
                disabled={!!loading || !text.trim()}
                data-testid={`cowriter-${a}`}
              >
                {loading === a ? "思考中…" : ACTION_LABEL[a]}
              </OButton>
            ))}
            {text.trim() && (
              <SaveToNotebook
                record={{ source_type: "cowriter", content: text, title: text.trim().slice(0, 20) || "写作草稿" }}
                label="草稿存到笔记本"
              />
            )}
          </div>
        </div>
      </OCard>

      {refusal && (
        <div className="rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800" data-testid="cowriter-refusal">
          ✋ {refusal}
        </div>
      )}
      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      {result && (
        <OCard data-testid="cowriter-result">
          <OCardHeader>
            <OCardTitle>
              {ACTION_LABEL[result.action]}建议
              <span className="ml-2 text-xs font-normal text-[var(--o-color-fg-muted,#888)]">
                {result.hunks.length} 处修改 · 已接受 {accepted.size}
              </span>
            </OCardTitle>
          </OCardHeader>
          <div className="px-4 pb-4 space-y-3">
            {result.hunks.length === 0 ? (
              <div className="text-sm">没有需要修改的地方，写得不错！</div>
            ) : (
              <div className="whitespace-pre-wrap rounded border p-3 text-sm leading-relaxed" data-testid="cowriter-diff">
                {result.segments.map((seg, i) => {
                  if (seg.type === "equal") return <span key={i}>{seg.text}</span>;
                  const h = hunkById.get(seg.hunk_id);
                  if (!h) return null;
                  const on = accepted.has(h.id);
                  return (
                    <span key={i} className="inline">
                      {h.before && (
                        <del className={on ? "bg-red-100 text-red-700" : "text-[var(--o-color-fg,#222)] no-underline"}>{h.before}</del>
                      )}
                      {h.after && on && <ins className="bg-green-100 text-green-800 no-underline">{h.after}</ins>}
                      <button
                        type="button"
                        onClick={() => toggle(h.id)}
                        className={`mx-0.5 rounded px-1 text-[10px] align-super ${on ? "bg-green-600 text-white" : "border"}`}
                        title={on ? "点击拒绝这处修改" : `点击接受：${h.after || "删除"}`}
                        data-testid="hunk-toggle"
                      >
                        {on ? "✓" : "✗"}
                      </button>
                    </span>
                  );
                })}
              </div>
            )}
            {result.truncated && (
              <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                建议超出了与你原文相称的长度，已截短（写作助手只润色你的文字，不替你写）。
              </div>
            )}
            {result.notes.length > 0 && (
              <ul className="list-disc pl-5 text-sm space-y-1">
                {result.notes.map((n, i) => (
                  <li key={i}>{n}</li>
                ))}
              </ul>
            )}
            <div className="flex flex-wrap gap-2">
              <OButton size="sm" variant="outline" onClick={() => setAccepted(new Set(result.hunks.map((h) => h.id)))}>
                全部接受
              </OButton>
              <OButton size="sm" variant="outline" onClick={() => setAccepted(new Set())}>
                全部拒绝
              </OButton>
              <OButton size="sm" onClick={applyToText} data-testid="cowriter-apply">
                应用到我的文字
              </OButton>
            </div>
            {result.citations.length > 0 && (
              <div className="space-y-2 border-t pt-3">
                <div className="text-sm font-medium">教材里的相关内容（仅供参考）</div>
                {result.citations.map((c) => (
                  <div key={c.id} className="text-xs">
                    <OBadge variant="outline" className="mr-1 text-[10px]">
                      {c.verified ? "已核对" : "未核对"}
                    </OBadge>
                    <span className="font-medium">{c.title}</span>：{c.highlight}
                  </div>
                ))}
              </div>
            )}
          </div>
        </OCard>
      )}
    </main>
  );
}
