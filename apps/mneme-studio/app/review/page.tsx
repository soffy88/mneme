"use client";

// /studio/review —— 10 分钟错题复习（移动端优先）。
//
// 会话数据来自 /v1/review/today；作答走 /v1/review/today/answer（服务端判分，
// 前端只提交字符串 + 用时）。answer_type="self" 的题没有确定性判分：先看答案，
// 再由学生自评（我做对了 / 我做错了）→ 带 self_grade 重新提交。

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState, OProgressBar } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { MathText } from "@/components/MathText";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  fetchQuestionImageUrl, reviewAnswer, reviewFinish, reviewToday,
  type ReviewAnswerResult, type ReviewFinishResult, type ReviewItem, type ReviewToday,
} from "@/lib/questions";

const CHOICES = ["A", "B", "C", "D"];

function mmss(total: number): string {
  const s = Math.max(0, total);
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

/** 带 token 取题目图片 → object URL（token 绝不进 URL）。 */
function RecordImage({ recordId, alt }: { recordId: string; alt: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let obj: string | null = null;
    let alive = true;
    fetchQuestionImageUrl(recordId)
      .then((u) => {
        obj = u;
        if (alive) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [recordId]);

  if (failed) {
    return <div className="text-sm text-[var(--muted-foreground,#888)]">（图片加载失败）</div>;
  }
  if (!url) {
    return <div className="text-sm text-[var(--muted-foreground,#888)]">图片加载中…</div>;
  }
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt={alt} className="mx-auto max-h-64 w-auto rounded-lg border object-contain" />
  );
}

export default function ReviewPage() {
  const [phase, setPhase] = useState<"start" | "session" | "finish">("start");
  const [today, setToday] = useState<ReviewToday | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [idx, setIdx] = useState(0);
  const [answer, setAnswer] = useState("");
  const [result, setResult] = useState<ReviewAnswerResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [remaining, setRemaining] = useState(0);
  const [answered, setAnswered] = useState(0);
  const [correct, setCorrect] = useState(0);
  const [finished, setFinished] = useState<ReviewFinishResult | null>(null);

  const itemStartRef = useRef<number>(0);
  const sessionStartRef = useRef<number>(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await reviewToday();
      setToday(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败，请重试");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    void load();
  }, [load]);

  // 倒计时：到 0 显示"时间到"，但不打断当前题（学生可以做完这一题）。
  useEffect(() => {
    if (phase !== "session") return;
    const id = setInterval(() => setRemaining((r) => (r > 0 ? r - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [phase]);

  const items = today?.items ?? [];
  const current: ReviewItem | null = phase === "session" ? items[idx] ?? null : null;
  const total = items.length;

  const start = useCallback(() => {
    if (!today || today.items.length === 0) return;
    setIdx(0);
    setAnswer("");
    setResult(null);
    setAnswered(0);
    setCorrect(0);
    setFinished(null);
    setRemaining(today.budget_seconds);
    sessionStartRef.current = Date.now();
    itemStartRef.current = Date.now();
    setPhase("session");
  }, [today]);

  const finishSession = useCallback(
    async (finalAnswered: number, finalCorrect: number) => {
      if (!today) return;
      const duration = Math.max(0, Math.round((Date.now() - sessionStartRef.current) / 1000));
      try {
        const r = await reviewFinish({
          session_id: today.session_id,
          answered: finalAnswered,
          correct: finalCorrect,
          duration_seconds: duration,
        });
        setFinished(r);
      } catch (e) {
        setError(e instanceof Error ? e.message : "结算失败");
      } finally {
        setPhase("finish");
      }
    },
    [today]
  );

  const applyResult = useCallback(
    (r: ReviewAnswerResult) => {
      setResult(r);
      if (!r.needs_self_grade) {
        const ok = r.is_correct === true;
        setAnswered((n) => n + 1);
        if (ok) setCorrect((n) => n + 1);
      }
    },
    []
  );

  const submit = useCallback(
    async (value: string, selfGrade: boolean | null = null) => {
      if (!today || !current) return;
      setBusy(true);
      setError(null);
      try {
        const r = await reviewAnswer({
          session_id: today.session_id,
          item_id: current.item_id,
          answer: value,
          duration_ms: Math.max(0, Date.now() - itemStartRef.current),
          self_grade: selfGrade,
        });
        applyResult(r);
      } catch (e) {
        setError(e instanceof Error ? e.message : "提交失败，请重试");
      } finally {
        setBusy(false);
      }
    },
    [today, current, applyResult]
  );

  const next = useCallback(() => {
    const n = idx + 1;
    setAnswer("");
    setResult(null);
    setError(null);
    if (n >= total) {
      void finishSession(answered, correct);
      return;
    }
    setIdx(n);
    itemStartRef.current = Date.now();
  }, [idx, total, answered, correct, finishSession]);

  const needsSelf = !!result?.needs_self_grade;
  const answeredDone = !!result && !result.needs_self_grade;
  const timeUp = remaining <= 0;

  return (
    <main className="mx-auto max-w-xl p-4 space-y-4" data-testid="review-root">
      <h1 className="text-2xl font-bold">10 分钟复习</h1>
      <ProductNav />

      {error && (
        <OCard>
          <div className="p-4 text-base text-[var(--destructive,#c00)]">{error}</div>
        </OCard>
      )}

      {phase === "start" && (
        <>
          {loading && (
            <OCard>
              <div className="p-4 text-base text-[var(--muted-foreground,#888)]">加载中…</div>
            </OCard>
          )}

          {!loading && today && total === 0 && (
            <OCard>
              <div className="p-4 space-y-4">
                <OEmptyState title="错题本是空的 🎉" description="拍一道不会的题，就开始了。" />
                <Link
                  href="/ask"
                  className="inline-flex min-h-[44px] items-center rounded-[var(--control-radius)] bg-[var(--primary)] px-4 text-base text-[var(--primary-foreground)]"
                >
                  去拍一道题
                </Link>
              </div>
            </OCard>
          )}

          {!loading && today && total > 0 && (
            <OCard>
              <div className="p-4 space-y-4">
                <p className="text-lg">
                  今天要复习 <span className="font-bold">{total}</span> 道错题，大约{" "}
                  {Math.round(today.budget_seconds / 60)} 分钟。
                </p>
                <div className="text-base text-[var(--muted-foreground,#888)]">
                  连续复习 {today.streak} 天
                </div>
                <OButton
                  size="lg"
                  className="w-full min-h-[52px] text-base"
                  data-testid="review-start"
                  onClick={start}
                >
                  开始
                </OButton>
              </div>
            </OCard>
          )}
        </>
      )}

      {phase === "session" && current && (
        <>
          {/* 粘性顶栏：倒计时 + 进度 */}
          <div className="sticky top-0 z-10 -mx-4 border-b bg-[var(--background)] px-4 py-3">
            <div className="flex items-center justify-between">
              <span
                className={`text-lg font-semibold tabular-nums ${
                  timeUp
                    ? "text-[var(--warning,#b70)]"
                    : remaining < 60
                      ? "text-[var(--warning,#b70)]"
                      : ""
                }`}
                data-testid="review-timer"
              >
                {timeUp ? "时间到" : mmss(remaining)}
              </span>
              <span className="text-base" data-testid="review-progress">
                第 {idx + 1}/{total} 题
              </span>
            </div>
            <div className="mt-2">
              <OProgressBar value={total ? (idx / total) * 100 : 0} size="sm" />
            </div>
          </div>

          <OCard>
            <OCardHeader>
              <OCardTitle>
                {current.subject ? `${current.subject} · ` : ""}
                {current.review_count > 0 ? `复习过 ${current.review_count} 次` : "新错题"}
              </OCardTitle>
            </OCardHeader>
            <div className="p-4 space-y-4">
              <div className="rounded-xl bg-[var(--muted,#f6f6f6)] p-4 text-lg">
                <MathText text={current.question_text} />
              </div>

              {current.has_image && current.image_record_id && (
                <RecordImage recordId={current.image_record_id} alt="题目图片" />
              )}

              {!result && current.answer_type === "self" && (
                <OButton
                  size="lg"
                  variant="outline"
                  className="w-full min-h-[52px] text-base"
                  disabled={busy}
                  onClick={() => void submit("")}
                >
                  想好了，看答案
                </OButton>
              )}

              {!result && current.answer_type === "choice" && (
                <div className="grid grid-cols-4 gap-2" data-testid="review-answer">
                  {CHOICES.map((c) => {
                    const active = answer === c;
                    return (
                      <button
                        key={c}
                        type="button"
                        aria-pressed={active}
                        className={`min-h-[56px] rounded-xl border text-lg ${
                          active
                            ? "bg-[var(--primary)] text-[var(--primary-foreground)] border-transparent"
                            : "bg-[var(--background)] border-[var(--border)]"
                        }`}
                        onClick={() => setAnswer(c)}
                      >
                        {c}
                      </button>
                    );
                  })}
                </div>
              )}

              {!result && current.answer_type === "numeric" && (
                <input
                  data-testid="review-answer"
                  inputMode="decimal"
                  className="min-h-[48px] w-full rounded-xl border px-3 text-base"
                  placeholder="写下你的答案"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              )}

              {!result && current.answer_type === "text" && (
                <input
                  data-testid="review-answer"
                  className="min-h-[48px] w-full rounded-xl border px-3 text-base"
                  placeholder="写下你的答案"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                />
              )}

              {!result && current.answer_type !== "self" && (
                <div className="flex gap-2">
                  <OButton
                    size="lg"
                    className="flex-1 min-h-[52px] text-base"
                    data-testid="review-submit"
                    loading={busy}
                    disabled={busy || !answer.trim()}
                    onClick={() => void submit(answer)}
                  >
                    提交
                  </OButton>
                  <OButton
                    variant="ghost"
                    className="min-h-[52px] text-base"
                    disabled={busy}
                    onClick={() => void submit("")}
                  >
                    不会，看答案
                  </OButton>
                </div>
              )}

              {/* 结果卡 */}
              {result && (
                <div className="space-y-3">
                  {!needsSelf && (
                    <div className="text-lg font-semibold">
                      {result.is_correct === true
                        ? "✅ 答对了"
                        : result.is_correct === false
                          ? "❌ 答错了"
                          : "已提交"}
                    </div>
                  )}

                  {result.graduated && (
                    <div className="rounded-lg bg-[var(--alert-success-bg,#eafbea)] p-3 text-base text-[var(--alert-success-fg,#0a5)]">
                      毕业了！这道题已掌握 🎓
                    </div>
                  )}

                  {result.correct_answer != null && result.correct_answer !== "" && (
                    <div className="rounded-xl border p-4 text-base">
                      <div className="mb-1 text-sm font-semibold">正确答案</div>
                      <MathText text={result.correct_answer} />
                    </div>
                  )}

                  {result.explanation && (
                    <div className="text-base whitespace-pre-wrap text-[var(--muted-foreground,#555)]">
                      {result.explanation}
                    </div>
                  )}

                  {needsSelf && (
                    <div className="space-y-2">
                      <div className="text-base">这道题没有标准判分，你自己评一评：</div>
                      <div className="flex gap-2">
                        <OButton
                          size="lg"
                          className="flex-1 min-h-[52px] text-base"
                          loading={busy}
                          disabled={busy}
                          onClick={() => void submit(answer, true)}
                        >
                          我做对了
                        </OButton>
                        <OButton
                          size="lg"
                          variant="outline"
                          className="flex-1 min-h-[52px] text-base"
                          disabled={busy}
                          onClick={() => void submit(answer, false)}
                        >
                          我做错了
                        </OButton>
                      </div>
                    </div>
                  )}

                  {answeredDone && (
                    <OButton
                      size="lg"
                      className="w-full min-h-[52px] text-base"
                      onClick={next}
                    >
                      {idx + 1 >= total ? "完成复习" : "下一题"}
                    </OButton>
                  )}
                </div>
              )}
            </div>
          </OCard>
        </>
      )}

      {phase === "finish" && (
        <OCard data-testid="review-finish">
          <div className="p-6 space-y-5 text-center">
            <div className="text-6xl" aria-hidden>🔥</div>
            <div className="text-2xl font-bold">
              连续复习 {finished?.streak ?? today?.streak ?? 0} 天
            </div>
            <div className="text-base">
              本轮作答 {answered} 题，答对 {correct} 题。
            </div>
            {finished?.message && <div className="text-base">{finished.message}</div>}
            {finished && finished.remaining_due > 0 && (
              <div className="text-base text-[var(--muted-foreground,#888)]">
                还有 {finished.remaining_due} 道等着复习
              </div>
            )}
            <div className="flex flex-col gap-2">
              <Link
                href="/ask"
                className="inline-flex min-h-[52px] items-center justify-center rounded-[var(--control-radius)] bg-[var(--primary)] px-4 text-base text-[var(--primary-foreground)]"
              >
                再拍一道题
              </Link>
              <Link
                href="/history"
                className="inline-flex min-h-[52px] items-center justify-center rounded-[var(--control-radius)] border border-[var(--border)] px-4 text-base"
              >
                看做题记录
              </Link>
            </div>
          </div>
        </OCard>
      )}
    </main>
  );
}
