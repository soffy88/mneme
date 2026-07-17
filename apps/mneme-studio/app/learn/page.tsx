"use client";

import { useCallback, useEffect, useState } from "react";
import {
  OButton, OCard, OCardHeader, OCardTitle, OTextInput, OProgress,
  OEmptyState,
} from "@helios/blocks";
import {
  mcp, getStudentId, getToken, redirectToLogin,
  type NextStep, type Mastery,
} from "@/lib/mcp";
import { MathText } from "@/components/MathText";

// 一套登录：student_id 取自 mneme 登录会话（mneme_user），**不再走 ?student=**。
// 学习路径 kcIds 允许 ?kcs= 覆盖；缺省给一组起步知识点，保证登录后进来即可用
// （路径持久化是 W2b 后续；届时改为按学生档案拉路径）。禁后门/预填答案。
//
// 缺省必须是**定量**知识点：定量题由内核确定性判分（SubmitAnswer→graded→清 pending→
// 自动续下一题），链路能推进。定性知识点（如 ku004 函数概念）要靠"定性 verifier"出裁决
// 才能清 pending，而真 verifier 尚未接线（W2b 后续）——缺省若用定性，提交后同一题会一直
// 复现="不动了"。故缺省用 ku001/002/003（定量，题库有题），并借多 KC 满足交错红线。
const DEFAULT_KCS = [
  "renjiao-math-g10-a-ku001",
  "renjiao-math-g10-a-ku002",
  "renjiao-math-g10-a-ku003",
];

function readCtx(): { studentId: string; kcIds: string[] } {
  if (typeof window === "undefined") return { studentId: "", kcIds: [] };
  const q = new URLSearchParams(window.location.search);
  const kcs = (q.get("kcs") || "").split(",").filter(Boolean);
  return {
    studentId: getStudentId() || "",
    kcIds: kcs.length > 0 ? kcs : DEFAULT_KCS,
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
    // 一套登录：未登录 mneme → 直接跳 mneme-web /login（不弹 studio 自己的登录）。
    if (!getToken() || !getStudentId()) {
      redirectToLogin();
      return;
    }
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
        // verifier 暂不可用（无 key/rubric）→ 交外部评判的退回态
        setFeedback({ ok: true, msg: "你的解释已提交，老师会评判后给你反馈。" });
      } else if (r.qualitative) {
        // 概念解释题：真 verifier 按 rubric 裁决
        setFeedback(r.is_correct
          ? { ok: true, msg: "你的理解讲清楚了 ✓ 继续下一个。" }
          : { ok: false, msg: "理解还差点意思，换个角度再讲讲，我们再来一题。" });
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
    // 登录会话读取中 / 未登录跳转中（useEffect 会重定向到 mneme /login）。
    return (
      <main className="mx-auto max-w-xl p-6" data-testid="learn-root">
        <OEmptyState title="正在进入学习…" description="正在读取你的登录信息。" />
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
                className="rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-4 text-lg"
                data-testid="prompt"
              >
                <MathText text={pq.prompt} />
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
