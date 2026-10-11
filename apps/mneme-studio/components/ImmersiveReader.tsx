"use client";

// ImmersiveReader —— /studio/book 的沉浸阅读模式（DeepTutor Immersive Reading 对标）。
//
// - 全屏、无干扰，一次只读一个内容块，顶部进度条；←/→ 翻块。
// - 两种来源：编译好的活书（GetBook 的章节/块）或没有活书时的教材原文分块
//   （GET /v1/reading/textbooks/{id}，分页懒加载）。
// - "检查一下"：只走既有 RequestQuestion → SubmitAnswer（唯一守卫写入路径），
//   本组件不判分、不碰 expected、不写掌握度。
// - "解释这句"：选中一句话 → 既有 /v1/chat/turn，把当前块作为上下文。
// - 阅读位置：PUT /v1/reading/position（只是进度，不是学习证据），下次打开接着读。
// - 每块底部：相关练习（/studio/practice、/studio/learn?kcs=）、相关实验、步骤动画。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MathText } from "@/components/MathText";
import { RelatedLabsFor } from "@/components/RelatedLabs";
import {
  chatTurn,
  getStudentId,
  mcp,
  readingPosition,
  readingTextbook,
  saveReadingPosition,
  type BookBlock,
  type BookDetail,
  type ReadingSourceKind,
} from "@/lib/mcp";

type UnitType = "text" | "figure" | "check" | "cards" | "guided";

interface Unit {
  index: number;
  blockId: string;
  type: UnitType;
  chapter: string | null;
  text: string;
  caption?: string;
  cards?: { front: string; back: string }[];
  kcIds: string[];
  page?: number | null;
}

export type ReaderSource =
  | { kind: "book"; book: BookDetail }
  | { kind: "textbook"; textbookId: string; title?: string };

const PAGE = 40;

function kcIdsOf(block: BookBlock): string[] {
  const p = block.payload ?? {};
  const out: string[] = [];
  const push = (v: unknown) => {
    if (typeof v === "string" && v && !out.includes(v)) out.push(v);
  };
  if (Array.isArray(p.kc_ids)) (p.kc_ids as unknown[]).forEach(push);
  const cites = [
    ...(Array.isArray(p.citations) ? (p.citations as { ku_id?: string }[]) : []),
    ...((block.citations ?? []) as unknown as { ku_id?: string }[]),
  ];
  cites.forEach((c) => push(c?.ku_id));
  return out.slice(0, 5);
}

/** 活书 → 线性阅读单元（跳过生成失败的块和空公式块）。 */
export function flattenBook(book: BookDetail): Unit[] {
  const units: Unit[] = [];
  for (const ch of book.chapters) {
    for (const b of ch.blocks) {
      if (b.status !== "ready") continue;
      const p = b.payload ?? {};
      const base = { blockId: b.block_id, chapter: ch.title, kcIds: kcIdsOf(b) };
      if (b.block_type === "text" || b.block_type === "callout") {
        const text = String(p.text ?? "").trim();
        if (text) units.push({ ...base, index: units.length, type: "text", text });
      } else if (b.block_type === "figure") {
        const latex = String(p.latex ?? "").trim();
        if (latex) units.push({ ...base, index: units.length, type: "figure", text: latex, caption: String(p.caption ?? "") });
      } else if (b.block_type === "quiz") {
        if (base.kcIds.length) units.push({ ...base, index: units.length, type: "check", text: "" });
      } else if (b.block_type === "flash_cards") {
        const cards = Array.isArray(p.cards)
          ? (p.cards as { front?: string; back?: string }[]).map((c) => ({ front: String(c.front ?? ""), back: String(c.back ?? "") }))
          : [];
        if (cards.length) units.push({ ...base, index: units.length, type: "cards", text: "", cards });
      } else if (b.block_type === "guided") {
        units.push({ ...base, index: units.length, type: "guided", text: "" });
      }
    }
  }
  return units;
}

// ── 检查一下：RequestQuestion → SubmitAnswer（与 /studio/practice 完全同一条路径）──
function CheckPanel({ kcIds, studentId }: { kcIds: string[]; studentId: string }) {
  const [attempt, setAttempt] = useState(0);
  const [q, setQ] = useState<{ id: string; prompt: string; qtype: string } | null>(null);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);

  async function pose() {
    setBusy(true);
    setFeedback(null);
    setAnswer("");
    try {
      const kc = kcIds[attempt % kcIds.length];
      const r = await mcp.requestQuestion(studentId, kc);
      if (r.error || !r.question_id || !r.prompt) setFeedback({ ok: false, msg: "这个知识点暂时出不了题，先接着读吧。" });
      else setQ({ id: r.question_id, prompt: r.prompt, qtype: r.qtype || "solve" });
      setAttempt((a) => a + 1);
    } catch (e) {
      setFeedback({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  async function submit() {
    if (!q || !answer.trim()) return;
    setBusy(true);
    try {
      const r = await mcp.submitAnswer(studentId, q.id, answer);
      if (r.needs_qualitative) setFeedback({ ok: true, msg: "你的解释已提交，评判后会给你反馈。" });
      else if (r.graded || r.qualitative) setFeedback(r.is_correct ? { ok: true, msg: "答对了！继续往下读 🎉" } : { ok: false, msg: "这道没答对，可以回头再读一遍这一段。" });
      else setFeedback({ ok: true, msg: "已提交。" });
      setQ(null);
      setAnswer("");
    } catch (e) {
      setFeedback({ ok: false, msg: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4 space-y-3" data-testid="reader-check">
      <div className="font-medium">✍️ 检查一下：这一段读懂了吗？</div>
      {q ? (
        <div className="space-y-3">
          <div className="text-base leading-7" data-testid="reader-check-prompt">
            <MathText text={q.prompt} />
          </div>
          {q.qtype === "open" ? (
            <textarea className="w-full min-h-[96px] rounded-lg border p-3" placeholder="用自己的话讲讲…" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          ) : (
            <input className="w-full rounded-lg border p-3" placeholder="写下你的答案" value={answer} onChange={(e) => setAnswer(e.target.value)} />
          )}
          <button type="button" data-testid="reader-check-submit" className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-40" disabled={busy || !answer.trim()} onClick={() => void submit()}>
            {busy ? "提交中…" : "提交"}
          </button>
        </div>
      ) : (
        <button type="button" data-testid="reader-check-pose" className="rounded-lg border bg-white px-4 py-2 text-sm disabled:opacity-40" disabled={busy} onClick={() => void pose()}>
          {busy ? "出题中…" : attempt === 0 ? "出一道题" : "再来一道"}
        </button>
      )}
      {feedback && (
        <div className={`text-sm ${feedback.ok ? "text-green-700" : "text-red-700"}`} data-testid="reader-check-feedback">
          {feedback.msg}
        </div>
      )}
    </div>
  );
}

function FlashCards({ cards }: { cards: { front: string; back: string }[] }) {
  const [flipped, setFlipped] = useState<Record<number, boolean>>({});
  return (
    <div className="grid gap-3 sm:grid-cols-2" data-testid="reader-cards">
      {cards.map((c, i) => (
        <button
          key={i}
          type="button"
          onClick={() => setFlipped((f) => ({ ...f, [i]: !f[i] }))}
          className="min-h-[96px] rounded-xl border bg-white p-4 text-left text-base leading-7 shadow-sm"
        >
          <div className="mb-1 text-xs text-[var(--o-color-fg-muted,#888)]">{flipped[i] ? "背面（点击翻回）" : "正面（点击翻看）"}</div>
          <MathText text={flipped[i] ? c.back : c.front} />
        </button>
      ))}
    </div>
  );
}

export function ImmersiveReader({ source, subject, onExit }: { source: ReaderSource; subject?: string; onExit: () => void }) {
  const sourceKind: ReadingSourceKind = source.kind;
  const sourceId = source.kind === "book" ? source.book.book_id : source.textbookId;
  const bookUnits = useMemo(() => (source.kind === "book" ? flattenBook(source.book) : null), [source]);
  const [tbUnits, setTbUnits] = useState<Map<number, Unit>>(new Map());
  const [tbTotal, setTbTotal] = useState<number | null>(null);
  const [tbTitle, setTbTitle] = useState<string>(source.kind === "textbook" ? source.title ?? "" : "");
  const [tbSubject, setTbSubject] = useState<string | undefined>(subject);
  const [idx, setIdx] = useState(0);
  const [ready, setReady] = useState(false);
  const [resumed, setResumed] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fontSize, setFontSize] = useState(19);
  const [showCheck, setShowCheck] = useState(false);
  const [showLabs, setShowLabs] = useState(false);
  const [sel, setSel] = useState<{ text: string; x: number; y: number } | null>(null);
  const [explain, setExplain] = useState<{ sentence: string; reply: string | null; error?: string } | null>(null);
  const loadingPages = useRef<Set<number>>(new Set());
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const studentId = typeof window !== "undefined" ? getStudentId() : null;

  const total = bookUnits ? bookUnits.length : tbTotal ?? 0;
  const title = source.kind === "book" ? source.book.title : tbTitle;
  const effSubject = source.kind === "book" ? source.book.subject ?? subject : tbSubject;
  const unit: Unit | undefined = bookUnits ? bookUnits[idx] : tbUnits.get(idx);

  const loadPage = useCallback(
    async (offset: number) => {
      if (source.kind !== "textbook" || loadingPages.current.has(offset)) return;
      loadingPages.current.add(offset);
      try {
        const page = await readingTextbook(source.textbookId, offset, PAGE);
        setTbTotal(page.total);
        setTbTitle(page.textbook.book_name);
        setTbSubject(page.textbook.subject);
        setTbUnits((prev) => {
          const next = new Map(prev);
          for (const b of page.blocks) {
            next.set(b.index, {
              index: b.index,
              blockId: b.block_id,
              type: "text",
              chapter: b.section_title,
              text: b.payload.text,
              kcIds: b.kc_ids,
              page: b.page_number,
            });
          }
          return next;
        });
      } catch (e) {
        loadingPages.current.delete(offset);
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [source],
  );

  // 初次：取阅读位置 → 定位（教材则加载那一页）
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      let start = 0;
      if (studentId) {
        try {
          const r = await readingPosition(studentId, sourceKind, sourceId);
          if (r.position && r.position.block_index > 0) start = r.position.block_index;
        } catch {
          /* 位置读不到不影响阅读 */
        }
      }
      if (source.kind === "textbook") {
        await loadPage(Math.floor(start / PAGE) * PAGE);
      }
      if (cancelled) return;
      setIdx(start);
      if (start > 0) setResumed(start);
      setReady(true);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sourceKind, sourceId]);

  // 位置越界（书变短了）→ 收回
  useEffect(() => {
    if (ready && total > 0 && idx >= total) setIdx(total - 1);
  }, [ready, total, idx]);

  // 教材：确保当前块和下一块所在页已加载
  useEffect(() => {
    if (source.kind !== "textbook" || !ready) return;
    for (const i of [idx, idx + 1]) {
      if (tbTotal !== null && i >= tbTotal) continue;
      if (!tbUnits.has(i)) void loadPage(Math.floor(i / PAGE) * PAGE);
    }
  }, [idx, ready, source.kind, tbUnits, tbTotal, loadPage]);

  // 保存阅读位置（防抖）
  useEffect(() => {
    if (!ready || !studentId || !unit || total <= 0) return;
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      void saveReadingPosition({ studentId, kind: sourceKind, sourceId, blockIndex: idx, blockId: unit.blockId, totalBlocks: total }).catch(() => undefined);
    }, 700);
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [ready, studentId, unit, idx, total, sourceKind, sourceId]);

  const go = useCallback(
    (n: number) => {
      if (n < 0 || (total > 0 && n >= total)) return;
      setIdx(n);
      setShowCheck(false);
      setShowLabs(false);
      setSel(null);
      setExplain(null);
      setResumed(null);
      window.scrollTo?.(0, 0);
    },
    [total],
  );

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA")) return;
      if (e.key === "ArrowRight") go(idx + 1);
      else if (e.key === "ArrowLeft") go(idx - 1);
      else if (e.key === "Escape" && !document.fullscreenElement) onExit();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, idx, onExit]);

  function onSelect() {
    const s = window.getSelection();
    const text = s?.toString().trim() ?? "";
    if (!s || s.rangeCount === 0 || text.length < 2 || text.length > 300) {
      setSel(null);
      return;
    }
    const range = s.getRangeAt(0);
    if (!contentRef.current || !contentRef.current.contains(range.commonAncestorContainer)) return;
    const rect = range.getBoundingClientRect();
    setSel({ text, x: rect.left + rect.width / 2, y: rect.top });
  }

  async function doExplain(sentence: string) {
    if (!studentId || !unit) return;
    setSel(null);
    setExplain({ sentence, reply: null });
    const context = (unit.text || unit.caption || "").slice(0, 1200);
    const message =
      `我正在读《${title}》${unit.chapter ? `「${unit.chapter}」` : ""}里的这一段：\n"""\n${context}\n"""\n` +
      `请结合这段内容，用简单易懂的话给我解释这句：「${sentence}」`;
    try {
      const r = await chatTurn<{ reply: string }>({
        student_id: studentId,
        message,
        history: [],
        ...(unit.kcIds.length ? { kc_ids: unit.kcIds } : {}),
      });
      setExplain({ sentence, reply: r.reply || "（没有拿到解释）" });
    } catch (e) {
      setExplain({ sentence, reply: null, error: e instanceof Error ? e.message : String(e) });
    }
  }

  function toggleFullscreen() {
    if (document.fullscreenElement) void document.exitFullscreen?.();
    else void document.documentElement.requestFullscreen?.().catch(() => undefined);
  }

  const pct = total > 0 ? Math.round(((idx + 1) / total) * 100) : 0;
  const learnHref = unit && unit.kcIds.length ? `/studio/learn?kcs=${encodeURIComponent(unit.kcIds.join(","))}` : "/studio/learn";
  const animatable = effSubject === "math" || effSubject === "physics" || effSubject === "chemistry";

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#fbfaf6] text-[#1f2328]" data-testid="immersive-reader">
      <div className="h-1 w-full bg-black/5">
        <div className="h-1 bg-amber-500 transition-all" style={{ width: `${pct}%` }} data-testid="reader-progress-bar" />
      </div>
      <header className="flex items-center gap-3 px-4 py-2 text-sm text-[#57606a]">
        <button type="button" data-testid="reader-exit" className="rounded px-2 py-1 hover:bg-black/5" onClick={onExit} aria-label="退出沉浸阅读">
          ✕
        </button>
        <div className="min-w-0 flex-1 truncate">
          <span className="font-medium text-[#1f2328]">{title}</span>
          {unit?.chapter && <span className="ml-2">· {unit.chapter}</span>}
        </div>
        <span data-testid="reader-progress">
          {total > 0 ? `${idx + 1} / ${total}` : "…"}
        </span>
        <button type="button" className="rounded px-2 py-1 hover:bg-black/5" onClick={() => setFontSize((f) => Math.max(15, f - 2))} aria-label="字号减小">
          A−
        </button>
        <button type="button" className="rounded px-2 py-1 hover:bg-black/5" onClick={() => setFontSize((f) => Math.min(28, f + 2))} aria-label="字号增大">
          A+
        </button>
        <button type="button" data-testid="reader-fullscreen" className="rounded px-2 py-1 hover:bg-black/5" onClick={toggleFullscreen}>
          ⛶ 全屏
        </button>
      </header>

      <main className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 pb-10 pt-6">
          {resumed !== null && (
            <div className="mb-4 rounded-lg bg-amber-100/70 px-3 py-2 text-sm" data-testid="reader-resumed">
              已回到上次读到的位置（第 {resumed + 1} 块）。
              <button type="button" className="ml-2 underline" onClick={() => go(0)}>
                从头读
              </button>
            </div>
          )}
          {error && <div className="mb-4 text-sm text-red-700">出错了：{error}</div>}
          {!ready || !unit ? (
            <div className="py-24 text-center text-[#57606a]">{ready && total === 0 ? "这本书暂时没有可读的内容。" : "正在打开…"}</div>
          ) : (
            <article key={unit.index} data-testid="reader-block" data-block-id={unit.blockId}>
              <div ref={contentRef} onMouseUp={onSelect} onTouchEnd={() => setTimeout(onSelect, 30)} style={{ fontSize, lineHeight: 1.9 }} className="whitespace-pre-line select-text">
                {unit.type === "text" && <MathText text={unit.text} />}
                {unit.type === "figure" && (
                  <div className="rounded-xl border bg-white p-6 text-center">
                    <MathText text={unit.text.includes("$") ? unit.text : `$$${unit.text}$$`} />
                    {unit.caption && <p className="mt-2 text-sm text-[#57606a]">{unit.caption}</p>}
                  </div>
                )}
                {unit.type === "cards" && unit.cards && <FlashCards cards={unit.cards} />}
                {unit.type === "guided" && (
                  <div className="rounded-xl border bg-white p-5 text-base">
                    🧭 这一章读完了。下一步按你的掌握情况安排学习：
                    <a href={learnHref} className="ml-2 underline" data-testid="reader-guided-link">
                      去学习
                    </a>
                  </div>
                )}
              </div>
              {unit.page != null && <div className="mt-3 text-xs text-[#8c959f]">教材第 {unit.page} 页（原文）</div>}

              {unit.type === "check" && studentId && <div className="mt-2"><CheckPanel kcIds={unit.kcIds} studentId={studentId} /></div>}
              {unit.type !== "check" && showCheck && studentId && unit.kcIds.length > 0 && (
                <div className="mt-6">
                  <CheckPanel kcIds={unit.kcIds} studentId={studentId} />
                </div>
              )}

              {explain && (
                <div className="mt-6 rounded-xl border border-sky-200 bg-sky-50/70 p-4 text-base leading-7" data-testid="reader-explain">
                  <div className="mb-2 text-sm text-[#57606a]">💡 「{explain.sentence.length > 60 ? `${explain.sentence.slice(0, 60)}…` : explain.sentence}」</div>
                  {explain.error ? (
                    <div className="text-sm text-red-700">解释暂时不可用：{explain.error}</div>
                  ) : explain.reply === null ? (
                    <div className="text-sm text-[#57606a]">正在想怎么讲清楚…</div>
                  ) : (
                    <div className="whitespace-pre-line" data-testid="reader-explain-reply">
                      <MathText text={explain.reply} />
                    </div>
                  )}
                  <button type="button" className="mt-2 text-sm underline" onClick={() => setExplain(null)}>
                    收起
                  </button>
                </div>
              )}

              <div className="mt-8 flex flex-wrap items-center gap-2 text-sm">
                {unit.type !== "check" && unit.kcIds.length > 0 && (
                  <button type="button" data-testid="reader-check-toggle" className="rounded-full border bg-white px-3 py-1" onClick={() => setShowCheck((v) => !v)}>
                    ✍️ 检查一下
                  </button>
                )}
                <a href="/studio/practice" className="rounded-full border bg-white px-3 py-1" data-testid="reader-practice-link">
                  📝 错题练习
                </a>
                {unit.kcIds.length > 0 && (
                  <a href={learnHref} className="rounded-full border bg-white px-3 py-1" data-testid="reader-learn-link">
                    📚 学这个知识点
                  </a>
                )}
                {animatable && (
                  <a href="/studio/animate" className="rounded-full border bg-white px-3 py-1" data-testid="reader-animate-link">
                    🎬 步骤动画
                  </a>
                )}
                <button type="button" data-testid="reader-labs-toggle" className="rounded-full border bg-white px-3 py-1" onClick={() => setShowLabs((v) => !v)}>
                  🔬 相关实验
                </button>
                <span className="text-xs text-[#8c959f]">选中一句话可以让我解释</span>
              </div>
              {showLabs && (
                <div className="mt-3" data-testid="reader-labs">
                  <RelatedLabsFor
                    q={(unit.text || unit.chapter || title).slice(0, 200)}
                    kcId={unit.kcIds[0]}
                    subject={effSubject}
                    limit={2}
                  />
                </div>
              )}
              {total > 0 && idx === total - 1 && (
                <div className="mt-10 rounded-xl border bg-white p-5 text-center" data-testid="reader-finished">
                  🎉 读完了！可以去
                  <a href="/studio/practice" className="mx-1 underline">
                    练一练
                  </a>
                  或者
                  <a href="/studio/path" className="mx-1 underline">
                    看看学习路径
                  </a>
                  。
                </div>
              )}
            </article>
          )}
        </div>
      </main>

      {sel && (
        <button
          type="button"
          data-testid="reader-explain-btn"
          className="fixed z-[60] -translate-x-1/2 -translate-y-full rounded-full bg-black px-3 py-1 text-sm text-white shadow-lg"
          style={{ left: sel.x, top: Math.max(8, sel.y - 8) }}
          onMouseDown={(e) => e.preventDefault()}
          onClick={() => void doExplain(sel.text)}
        >
          💡 解释这句
        </button>
      )}

      <footer className="flex items-center justify-between gap-3 border-t border-black/5 px-4 py-3">
        <button type="button" data-testid="reader-prev" className="rounded-lg border bg-white px-4 py-2 text-sm disabled:opacity-40" disabled={idx <= 0} onClick={() => go(idx - 1)}>
          ← 上一块
        </button>
        <span className="text-xs text-[#8c959f]">← → 键翻页 · Esc 退出</span>
        <button type="button" data-testid="reader-next" className="rounded-lg bg-black px-4 py-2 text-sm text-white disabled:opacity-40" disabled={total === 0 || idx >= total - 1} onClick={() => go(idx + 1)}>
          下一块 →
        </button>
      </footer>
    </div>
  );
}
