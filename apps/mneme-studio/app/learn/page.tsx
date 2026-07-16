"use client";

import { useCallback, useEffect, useState } from "react";
import {
  OButton, OCard, OCardHeader, OCardTitle, OTextInput, OProgress,
  OEmptyState,
} from "@helios/blocks";
import { mcp, type NextStep, type Mastery } from "@/lib/mcp";

// student_id + 学习路径来自 URL query（登录后重定向携带；测试传入）。禁后门/预填答案。
function readCtx(): { studentId: string; kcIds: string[] } {
  if (typeof window === "undefined") return { studentId: "", kcIds: [] };
  const q = new URLSearchParams(window.location.search);
  return {
    studentId: q.get("student") || "",
    kcIds: (q.get("kcs") || "").split(",").filter(Boolean),
  };
}

const ACTION_LABEL: Record<string, string> = {
  probe: "认识新知识点", practice: "练习", review: "复习", assess: "讲讲你的理解",
  answer_pending: "作答", complete: "全部学完", review_due: "有复习到期",
};

export default function LearnPage() {
  const [ctx, setCtx] = useState({ studentId: "", kcIds: [] as string[] });
  const [step, setStep] = useState<NextStep | null>(null);
  const [question, setQuestion] = useState<
    { question_id: string; prompt: string; qtype: string } | null
  >(null);
  const [mastery, setMastery] = useState<Mastery | null>(null);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (c: { studentId: string; kcIds: string[] }) => {
    if (!c.studentId || c.kcIds.length === 0) return;
    setError(null);
    try {
      const s = await mcp.nextObjective(c.studentId, c.kcIds);
      setStep(s);
      if (s.kc_id) setMastery(await mcp.checkMastery(c.studentId, s.kc_id));
      // 人在环出题：complete→无题；已有待答题→用它；否则自动请求下一题（RequestQuestion）。
      if (s.action === "complete" || !s.kc_id) {
        setQuestion(null);
      } else if (s.has_pending && s.pending_question) {
        setQuestion(s.pending_question);
      } else {
        const q = await mcp.requestQuestion(c.studentId, s.kc_id);
        setQuestion(
          q.error || !q.question_id || !q.prompt
            ? null
            : { question_id: q.question_id, prompt: q.prompt, qtype: q.qtype || "solve" }
        );
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    const c = readCtx();
    setCtx(c);
    void refresh(c);
  }, [refresh]);

  const submit = useCallback(async () => {
    if (!question || !answer.trim()) return;
    setBusy(true);
    setFeedback(null);
    try {
      const r = await mcp.submitAnswer(ctx.studentId, question.question_id, answer);
      if (r.needs_qualitative) {
        setFeedback({ ok: true, msg: "你的解释已提交，老师会评判后给你反馈。" });
      } else if (r.graded) {
        setFeedback(r.is_correct
          ? { ok: true, msg: "答对了！继续保持 🎉" }
          : { ok: false, msg: "这道没答对，别灰心，我们再来一道。" });
      }
      setAnswer("");
      await refresh(ctx); // 自动拉下一题（人在环连续作答，不需刷新）
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [question, answer, ctx, refresh]);

  if (!ctx.studentId || ctx.kcIds.length === 0) {
    return (
      <main className="mx-auto max-w-xl p-6" data-testid="learn-root">
        <OEmptyState
          title="还没有学习任务"
          description="请从登录后的入口进入学习（需要 ?student= 与 ?kcs= 参数）。"
        />
      </main>
    );
  }

  const pq = question;
  const action = step?.action ?? "";

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="learn-root">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">善学记 · 学习</h1>
        <OButton size="sm" onClick={() => void refresh(ctx)} data-testid="refresh">
          刷新
        </OButton>
      </header>

      {error && (
        <OCard data-testid="error"><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>
      )}

      {/* 掌握度进度 */}
      {mastery && (
        <OCard data-testid="mastery">
          <div className="p-4 space-y-2">
            <div className="flex items-center gap-2">
              <span className="text-sm text-[var(--o-color-fg-muted,#666)]">{step?.kc_name ?? mastery.kc_id}</span>
              <span
                className="rounded-full px-2 py-0.5 text-xs"
                style={{
                  background: mastery.is_mastered
                    ? "var(--o-color-success-subtle,#e6f7e6)"
                    : "var(--o-color-bg-subtle,#eee)",
                }}
                data-testid="gate-state"
              >
                {mastery.is_mastered ? "已过门" : "学习中"}
              </span>
            </div>
            <OProgress value={Math.round((mastery.p_learned_lower_bound || 0) * 100)} data-testid="mastery-bar" />
            <div className="text-xs text-[var(--o-color-fg-muted,#888)]" data-testid="mastery-stats">
              掌握下界 {Math.round((mastery.p_learned_lower_bound || 0) * 100)}% · 作答 {mastery.n_obs} 次
            </div>
          </div>
        </OCard>
      )}

      {step?.review_task && (
        <OCard data-testid="review-due"><div className="p-3 text-sm">📎 有到期复习，先把它巩固一下。</div></OCard>
      )}

      {/* 主面：当前动作 + 待答题 */}
      <OCard data-testid="objective">
        <OCardHeader><OCardTitle>{ACTION_LABEL[action] ?? action}</OCardTitle></OCardHeader>
        <div className="p-4 space-y-4">
          {action === "complete" && (
            <div className="text-center py-8 text-lg" data-testid="complete">🎉 这些知识点都学完啦！</div>
          )}

          {pq ? (
            <div className="space-y-3" data-testid="question">
              <div
                className="rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-4 whitespace-pre-wrap text-lg"
                data-testid="prompt"
              >
                {pq.prompt}
              </div>

              {pq.qtype === "open" ? (
                <textarea
                  className="w-full min-h-[120px] rounded-lg border p-3"
                  placeholder="用自己的话讲讲你的理解…"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  data-testid="answer-open"
                />
              ) : (
                <OTextInput
                  placeholder="在这里作答…"
                  value={answer}
                  onChange={(e) => setAnswer(e.target.value)}
                  data-testid="answer-input"
                />
              )}

              <OButton onClick={() => void submit()} disabled={busy || !answer.trim()} data-testid="submit">
                {busy ? "提交中…" : "提交"}
              </OButton>
            </div>
          ) : action !== "complete" ? (
            <div className="text-sm text-[var(--o-color-fg-muted,#888)]" data-testid="waiting">
              老师正在准备下一道题…（点“刷新”看看）
            </div>
          ) : null}

          {feedback && (
            <div
              className={`text-sm ${feedback.ok ? "text-[var(--o-color-success,#0a0)]" : "text-[var(--o-color-warning,#b70)]"}`}
              data-testid="feedback"
            >
              {feedback.msg}
            </div>
          )}
        </div>
      </OCard>
    </main>
  );
}
