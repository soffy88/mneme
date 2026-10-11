"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState, OTextInput } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { MathText } from "@/components/MathText";
import {
  getStudentId, getToken, mcp, redirectToLogin,
  type PracticeQueue, type PracticeKc,
} from "@/lib/mcp";

// 错题复习练习：队列 = FSRS 到期的知识点（服务端排程）+ 本人错题（不含答案）。
// 每一题都走既有 RequestQuestion → SubmitAnswer（服务端判分 + 守卫写入掌握度），
// 前端不判分、不接触答案；答完后由内核重新排程下次复习时间。

type Target = { kc_id: string; name: string; sample?: string | null };
type Q = { question_id: string; prompt: string; qtype: string };

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleString("zh-CN", { hour12: false, month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function PracticePage() {
  const [sid, setSid] = useState("");
  const [queue, setQueue] = useState<PracticeQueue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<Target[] | null>(null);
  const [idx, setIdx] = useState(0);
  const [question, setQuestion] = useState<Q | null>(null);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState({ answered: 0, correct: 0 });

  const loadQueue = useCallback(async (s: string) => {
    try { setQueue(await mcp.practiceQueue(s)); setError(null); }
    catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }, []);

  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    const s = getStudentId()!;
    setSid(s);
    void loadQueue(s);
  }, [loadQueue]);

  const pose = useCallback(async (t: Target) => {
    setQuestion(null); setFeedback(null); setAnswer("");
    try {
      const q = await mcp.requestQuestion(sid, t.kc_id);
      if (q.error || !q.question_id || !q.prompt) {
        setFeedback({ ok: false, msg: "这个知识点暂时出不了题，先跳过。" });
      } else {
        setQuestion({ question_id: q.question_id, prompt: q.prompt, qtype: q.qtype || "solve" });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [sid]);

  const start = useCallback((targets: Target[]) => {
    if (targets.length === 0) return;
    setSession(targets); setIdx(0); setDone({ answered: 0, correct: 0 });
    void pose(targets[0]);
  }, [pose]);

  const next = useCallback(() => {
    if (!session) return;
    const n = idx + 1;
    if (n >= session.length) {
      setSession(null); setQuestion(null); setFeedback(null);
      void loadQueue(sid);
      return;
    }
    setIdx(n);
    void pose(session[n]);
  }, [session, idx, pose, loadQueue, sid]);

  const submit = useCallback(async () => {
    if (!question || !answer.trim()) return;
    setBusy(true);
    try {
      const r = await mcp.submitAnswer(sid, question.question_id, answer);
      const ok = !!r.is_correct;
      if (r.needs_qualitative) setFeedback({ ok: true, msg: "你的解释已提交，老师会评判后给你反馈。" });
      else if (r.graded || r.qualitative) setFeedback(ok ? { ok: true, msg: "答对了！这次复习巩固住了 🎉" } : { ok: false, msg: "这道没答对，Mneme 会安排更早再复习它。" });
      else setFeedback({ ok: true, msg: "已提交。" });
      setDone((d) => ({ answered: d.answered + 1, correct: d.correct + (ok ? 1 : 0) }));
      setQuestion(null);
      setAnswer("");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [question, answer, sid]);

  const toTarget = (k: PracticeKc): Target => ({ kc_id: k.kc_id, name: k.name, sample: k.sample_wrong_question });
  const current = session ? session[idx] : null;

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="practice-root">
      <h1 className="text-2xl font-bold">错题复习</h1>
      <ProductNav />
      {error && <OCard><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>}

      {current && (
        <OCard data-testid="practice-session">
          <OCardHeader><OCardTitle>{current.name}（{idx + 1}/{session!.length}）</OCardTitle></OCardHeader>
          <div className="p-4 space-y-4">
            {current.sample && (
              <details className="text-sm">
                <summary className="cursor-pointer text-[var(--o-color-fg-muted,#666)]">你之前在这里错过的题</summary>
                <div className="pt-2"><MathText text={current.sample} /></div>
              </details>
            )}
            {question ? (
              <div className="space-y-3">
                <div className="rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-4 text-lg" data-testid="practice-prompt"><MathText text={question.prompt} /></div>
                {question.qtype === "open" ? (
                  <textarea className="w-full min-h-[120px] rounded-lg border p-3" placeholder="用自己的话讲讲你的理解…" value={answer} onChange={(e) => setAnswer(e.target.value)} />
                ) : (
                  <OTextInput placeholder="先自己回忆、作答…" value={answer} onChange={(e) => setAnswer(e.target.value)} />
                )}
                <div className="flex gap-2">
                  <OButton onClick={() => void submit()} disabled={busy || !answer.trim()} data-testid="practice-submit">{busy ? "提交中…" : "提交"}</OButton>
                  <OButton variant="ghost" onClick={next}>跳过</OButton>
                </div>
              </div>
            ) : !feedback ? (
              <div className="text-sm text-[var(--o-color-fg-muted,#888)]">正在准备题目…</div>
            ) : null}
            {feedback && (
              <div className="space-y-3">
                <div className={`text-sm ${feedback.ok ? "text-[var(--o-color-success,#0a0)]" : "text-[var(--o-color-warning,#b70)]"}`} data-testid="practice-feedback">{feedback.msg}</div>
                <OButton onClick={next}>{idx + 1 >= session!.length ? "完成本轮" : "下一题"}</OButton>
              </div>
            )}
          </div>
        </OCard>
      )}

      {!session && done.answered > 0 && (
        <OCard><div className="p-4 text-sm">本轮完成：作答 {done.answered} 题，答对 {done.correct} 题。下次复习时间已由 Mneme 重新安排。</div></OCard>
      )}

      {!session && queue && (
        <>
          <OCard data-testid="practice-due">
            <OCardHeader><OCardTitle>今天该复习的（{queue.due_count}）</OCardTitle></OCardHeader>
            <div className="p-4 space-y-3">
              {queue.due.length === 0 ? (
                <div className="text-sm text-[var(--o-color-fg-muted,#666)]">
                  暂时没有到期的复习 ✓{queue.upcoming[0] ? ` 下一个：${queue.upcoming[0].name}（${when(queue.upcoming[0].due_at)}）` : ""}
                </div>
              ) : (
                <>
                  <OButton onClick={() => start(queue.due.slice(0, 10).map(toTarget))} data-testid="practice-start">开始复习（{Math.min(queue.due.length, 10)} 题）</OButton>
                  <ul className="space-y-2">
                    {queue.due.map((k) => (
                      <li key={k.kc_id} className="flex items-center justify-between rounded-lg border p-3 text-sm">
                        <div>
                          <div className="font-medium">{k.name}</div>
                          <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                            {k.overdue_hours >= 24 ? `已逾期 ${Math.floor(k.overdue_hours / 24)} 天` : "今天到期"}{k.wrong_count ? ` · 错过 ${k.wrong_count} 次` : ""}
                          </div>
                        </div>
                        <OButton size="sm" variant="outline" onClick={() => start([toTarget(k)])}>练这个</OButton>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </OCard>

          {queue.upcoming.length > 0 && (
            <OCard>
              <OCardHeader><OCardTitle>即将到期</OCardTitle></OCardHeader>
              <ul className="p-4 space-y-1 text-sm">
                {queue.upcoming.map((k) => (
                  <li key={k.kc_id} className="flex justify-between"><span>{k.name}</span><span className="text-[var(--o-color-fg-muted,#888)]">{when(k.due_at)}</span></li>
                ))}
              </ul>
            </OCard>
          )}

          <OCard data-testid="practice-wrong">
            <OCardHeader><OCardTitle>我的错题本</OCardTitle></OCardHeader>
            <div className="p-4 space-y-3">
              {queue.wrong_questions.length === 0 ? (
                <OEmptyState title="还没有错题" description="答错的题会自动收进这里，并按遗忘曲线安排复习。" />
              ) : queue.wrong_questions.map((w) => (
                <div key={w.id} className="rounded-lg border p-3 space-y-2">
                  <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                    {w.ku_name ?? "未归类"} · 错 {w.wrong_count} 次{w.kc_due ? " · 到期复习" : ""}{w.last_wrong_at ? ` · ${when(w.last_wrong_at)}` : ""}
                  </div>
                  <div className="text-sm line-clamp-3">{w.has_image ? "（含图题，图片暂无法在此显示）" : <MathText text={w.question_text} />}</div>
                  {w.ku_id && (
                    <OButton size="sm" variant="outline" onClick={() => start([{ kc_id: w.ku_id!, name: w.ku_name ?? w.ku_id!, sample: w.has_image ? null : w.question_text }])}>
                      练同类题
                    </OButton>
                  )}
                </div>
              ))}
            </div>
          </OCard>
          <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
            想按顺序推进新知识点？去 <Link href="/path" className="underline">掌握路径</Link>。
          </div>
        </>
      )}
    </main>
  );
}
