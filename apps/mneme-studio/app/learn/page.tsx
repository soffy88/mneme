"use client";

import { useCallback, useEffect, useState } from "react";
import {
  OButton, OCard, OCardHeader, OCardTitle, OTextInput,
  OEmptyState,
} from "@helios/blocks";
import {
  mcp, getStudentId, getToken, pathLockedInfo, redirectToLogin,
  type NextStep, type Mastery,
  type LearnNowView, type PathLockedInfo,
} from "@/lib/mcp";
import { MathText } from "@/components/MathText";
import { BookmarkStar } from "@/components/BookmarkStar";
import { QuickStart } from "@/components/QuickStart";
import { ProductNav } from "@/components/ProductNav";
import Link from "next/link";
import { reviewToday, type ReviewToday } from "@/lib/questions";

// 一套登录：student_id 取自 mneme 登录会话（mneme_user），**不再走 ?student=**。
// 学习路径（AA.5）：默认经 GetPath 按学生档案拉（有内容的 KC、按章节序）；`?kcs=` 仍可覆盖；
// GetPath 失败/空时回落 DEFAULT_KCS。禁后门/预填答案。
//
// DEFAULT_KCS 仅作兜底：ku001–003 定量 + ku004 定性（概念解释，走真 verifier），
// 一条路径即可测两类判分。
const DEFAULT_KCS = [
  "renjiao-math-g10-a-ku001",
  "renjiao-math-g10-a-ku002",
  "renjiao-math-g10-a-ku003",
  "renjiao-math-g10-a-ku004",
];

function urlKcs(): string[] {
  if (typeof window === "undefined") return [];
  return (new URLSearchParams(window.location.search).get("kcs") || "")
    .split(",")
    .filter(Boolean);
}

const REASON_LABEL: Record<string, string> = {
  expected_gain_per_minute: "现在花一分钟，收获最大",
  retrieval_urgency: "快要忘了，正是复习的好时候",
  transfer_evidence_gap: "还没在新题里用过，练一练才算真会",
  high_uncertainty_diagnostic: "还不确定你会不会，先测一测",
};

function reasonText(codes: string[]): string {
  const zh = codes.map((c) => REASON_LABEL[c]).filter(Boolean);
  return zh.length ? zh.join("；") : "根据你最近的作答挑的下一步";
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
  const [learnNow, setLearnNow] = useState<LearnNowView | null>(null);
  const [answer, setAnswer] = useState("");
  const [feedback, setFeedback] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState<PathLockedInfo | null>(null);
  const [todayReview, setTodayReview] = useState<ReviewToday | null>(null);
  const [reviewLoading, setReviewLoading] = useState(true);

  const refresh = useCallback(async (c: { studentId: string; kcIds: string[] }) => {
    if (!c.studentId || c.kcIds.length === 0) return;
    setError(null);
    setLocked(null);
    try {
      const s = await mcp.nextObjective(c.studentId, c.kcIds);
      setStep(s);
      try {
        const productView = await mcp.productLearnNow(c.studentId);
        setLearnNow(productView);
      } catch {
        // The existing learning path remains usable if the product projection
        // is temporarily unavailable; it never makes a local policy choice.
        setLearnNow(null);
      }
      if (s.kc_id) setMastery(await mcp.checkMastery(c.studentId, s.kc_id));
      // 人在环出题：complete→无题；已有待答题→用它；否则自动请求下一题（RequestQuestion）。
      if (s.action === "complete" || !s.kc_id) {
        setQuestion(null);
      } else if (s.has_pending && s.pending_question) {
        setQuestion(s.pending_question);
      } else {
        let q;
        try {
          q = await mcp.requestQuestion(c.studentId, s.kc_id);
        } catch (e) {
          // 服务端路径锁：current 之前不能开新知识点（复习/练习不受影响）。
          const info = pathLockedInfo(e);
          if (!info) throw e;
          setLocked(info);
          setQuestion(null);
          return;
        }
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
    void reviewToday()
      .then((data) => setTodayReview(data))
      .catch(() => setTodayReview(null))
      .finally(() => setReviewLoading(false));
    void (async () => {
      const sid = getStudentId() || "";
      let kcIds = urlKcs(); // ?kcs= 覆盖优先
      if (kcIds.length === 0) {
        try {
          const path = await mcp.getPath(sid); // AA.5：按学生档案拉路径
          kcIds = path.kc_ids?.length ? path.kc_ids : DEFAULT_KCS;
        } catch {
          kcIds = DEFAULT_KCS; // GetPath 失败 → 兜底
        }
      }
      const c = { studentId: sid, kcIds };
      setCtx(c);
      void mcp.productEvent(sid, "learning_session_started", kcIds).catch(() => undefined);
      void refresh(c);
    })();
  }, [refresh]);

  const submit = useCallback(async () => {
    if (!question || !answer.trim()) return;
    setBusy(true);
    setFeedback(null);
    try {
      const r = await mcp.submitAnswer(ctx.studentId, question.question_id, answer);
      void mcp.productEvent(ctx.studentId, "next_best_action_completed", step?.kc_id ? [step.kc_id] : [], learnNow?.policy_decision_id ?? undefined).catch(() => undefined);
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
        <h1 className="text-2xl font-bold">善学记 · 马上学</h1>
        <OButton size="sm" className="min-h-[44px]" onClick={() => void refresh(ctx)} data-testid="refresh">
          刷新
        </OButton>
      </header>

      <ProductNav />

      <OCard data-testid="today-review">
        <div className="space-y-3 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h2 className="text-xl font-bold">今日 10 分钟</h2>
              <p className="mt-1 text-sm text-[var(--o-color-fg-muted,#777)]">每天复习一点，把学过的知识记得更牢。</p>
            </div>
            {todayReview && <span className="shrink-0 text-sm font-semibold">🔥 连续 {todayReview.streak} 天</span>}
          </div>
          {reviewLoading ? (
            <p className="text-base text-[var(--o-color-fg-muted,#777)]">正在读取今日复习…</p>
          ) : todayReview ? (
            todayReview.items.length > 0 ? (
              <p className="text-base">还有 <span className="font-bold">{todayReview.items.length}</span> 道错题待复习</p>
            ) : (
              <p className="text-base font-semibold">今天的错题都复习完了</p>
            )
          ) : (
            <p className="text-base text-[var(--o-color-fg-muted,#777)]">今日复习暂时无法读取，打开复习页重试。</p>
          )}
          <Link
            href={todayReview && todayReview.items.length === 0 ? "/ask" : "/review"}
            className="flex min-h-[52px] w-full items-center justify-center rounded-xl bg-[var(--o-color-primary,#2458d3)] px-4 text-base font-semibold text-white"
          >
            {todayReview && todayReview.items.length === 0 ? "拍一道题" : "开始今日复习"}
          </Link>
        </div>
      </OCard>

      <QuickStart />

      {error && (
        <OCard data-testid="error"><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>
      )}

      {/* 状态标签来自服务端；前端不计算掌握度或选择策略。 */}
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
            <div className="text-xs text-[var(--o-color-fg-muted,#888)]" data-testid="mastery-stats">
              状态由 Mneme 的认知模型提供 · 证据记录 {mastery.n_obs} 次
            </div>
          </div>
        </OCard>
      )}

      {learnNow && (
        <OCard data-testid="why-this">
          <div className="p-4 space-y-2">
            <div className="font-semibold">为什么先学这个？</div>
            {learnNow.status === "CAUGHT_UP" ? (
              <div className="text-sm">都跟上了，可以歇一歇 🎉</div>
            ) : (
              <>
                <div className="text-sm">
                  {reasonText(learnNow.reason_codes)}
                </div>
              </>
            )}
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

          {locked && (
            <div className="space-y-2 rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-4" data-testid="path-locked">
              <div className="text-sm">🔒 {locked.message}</div>
              <div className="flex gap-3 text-sm">
                <button type="button" className="underline" onClick={() => { if (window.location.search) window.location.assign(window.location.pathname); else void refresh(ctx); }}>学当前知识点</button>
                <Link href="/path" className="underline">看掌握路径</Link>
              </div>
            </div>
          )}

          {pq ? (
            <div className="space-y-3" data-testid="question">
              <div
                className="rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-4 text-lg"
                data-testid="prompt"
              >
                <MathText text={pq.prompt} />
              </div>
              <div className="flex justify-end">
                <BookmarkStar studentId={ctx.studentId} source="posed" questionId={pq.question_id} />
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
          ) : action !== "complete" && !locked ? (
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
