"use client";

// /studio/ask —— 拍照问题目（移动端优先，单屏分步）。
//
// 数据通道是 lib/questions.ts（/v1/questions/*）。前端只上传图片/文字、展示内核与
// LLM 的返回；不判分、不生成答案。图片在**客户端**裁剪 + 旋转 + 缩放到长边 1600 再上传
// （components/ask/ImagePrep.ts，EXIF orientation 已应用），取原图时带 token 换
// blob → object URL（token 绝不进 URL）。
//
// 步骤：选图 → 裁剪 → 选行（有 lines 时）→ 确认题干 → 解题 → 结果。

import { useCallback, useEffect, useRef, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { MathText } from "@/components/MathText";
import { subjectLabel } from "@/lib/format";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  askFollowup, askFeedback, askQuestion, addToWrongbook, solveAsk,
  type AskResult, type AskSolveResult,
} from "@/lib/questions";
import { CameraButton } from "@/components/ask/CameraButton";
import { CropBox, type CropRect } from "@/components/ask/CropBox";
import { LineTapper } from "@/components/ask/LineTapper";
import { MathKeyboard } from "@/components/ask/MathKeyboard";
import { AnswerCard, solverLabel, kernelLabel } from "@/components/ask/AnswerCard";
import { ReportWrong } from "@/components/ask/ReportWrong";
import { WaitSkeleton } from "@/components/ask/WaitSkeleton";
import { prepImage } from "@/components/ask/ImagePrep";

const SUBJECTS = ["数学", "物理", "化学", "英语", "语文", "其他"];

/** 已解码的原图（裁剪用）：object URL + 自然像素尺寸。 */
interface Picked {
  url: string;
  width: number;
  height: number;
}

type Phase = "idle" | "picking" | "cropping" | "lines" | "recognizing" | "confirm" | "solving" | "done";
type RetryKind = "recognize" | "solve" | null;
type ChatMsg = { role: "me" | "ai"; text: string };

// 后端 /solve 的扩展字段（services/photo_ask_service.solve_question 的文档）：
// status="multi" → questions；status="no_exact_solver" → similar / references。
type AskQuestionItem = { index: number; label: string; text: string; solvable: boolean; kernel: string | null };
type AskSimilarItem = { text: string; answer: string; steps?: string[]; hint?: string | null; score?: number };
type AskReference = { content: string; book_name?: string | null; page_number?: number | null };
type AskSolveExtra = AskSolveResult & {
  questions?: AskQuestionItem[];
  similar?: AskSimilarItem[];
  references?: AskReference[];
};

export default function AskPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [subject, setSubject] = useState<string | null>(null);

  // 原图（未裁剪，仅解码）：交给 CropBox 显示 + 取自然尺寸；裁剪+缩放+编码后才上传。
  const [picked, setPicked] = useState<Picked | null>(null);
  const [sourceBlob, setSourceBlob] = useState<Blob | null>(null);
  const [showTyped, setShowTyped] = useState(false);
  const [typedText, setTypedText] = useState("");

  const [ask, setAsk] = useState<AskResult | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [solve, setSolve] = useState<AskSolveResult | null>(null);
  const confirmRef = useRef<HTMLTextAreaElement>(null);

  const [elapsed, setElapsed] = useState(0);
  const [showSteps, setShowSteps] = useState(false);
  const [showAnswer, setShowAnswer] = useState(false);

  const [feedback, setFeedback] = useState<"understood" | "not_understood" | null>(null);
  const [wrongbookAdded, setWrongbookAdded] = useState(false);
  const [wrongbookBusy, setWrongbookBusy] = useState(false);

  const [chat, setChat] = useState<ChatMsg[]>([]);
  const [chatInput, setChatInput] = useState("");
  const [chatBusy, setChatBusy] = useState(false);

  const [error, setError] = useState<string | null>(null);
  const [retryKind, setRetryKind] = useState<RetryKind>(null);

  useEffect(() => {
    if (!getToken()) redirectToLogin();
  }, []);

  // 识别 / 解题都在等，一个计时器两处用。
  const waiting = phase === "recognizing" || phase === "solving";
  useEffect(() => {
    if (!waiting) return;
    setElapsed(0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [waiting]);

  // 原图 object URL 生命周期。
  useEffect(() => {
    if (!picked) return;
    return () => URL.revokeObjectURL(picked.url);
  }, [picked]);

  /** 选到文件 → 解码出自然尺寸 → 进裁剪步（打字输入跳过这些）。 */
  const pickFile = useCallback(async (file: File | null) => {
    if (!file) return;
    setError(null);
    setRetryKind(null);
    try {
      const { width, height } = await prepImage(file, { maxSide: 1600 });
      const url = URL.createObjectURL(file);
      setPicked((prev) => {
        if (prev) URL.revokeObjectURL(prev.url);
        return { url, width, height };
      });
      setSourceBlob(null);
      setPhase("cropping");
    } catch (e) {
      setError(e instanceof Error ? e.message : "图片处理失败");
    }
  }, []);

  /** 裁剪确认 → 编码（裁剪 + 缩放 + JPEG）→ 有 lines 的服务端会在识别后给行。 */
  const applyCrop = useCallback(
    async (crop: CropRect | null) => {
      if (!picked) return;
      setError(null);
      try {
        const res = await fetch(picked.url);
        const file = await res.blob();
        const out = await prepImage(file, { maxSide: 1600, crop });
        setSourceBlob(out.blob);
        setPhase("idle");
      } catch (e) {
        setError(e instanceof Error ? e.message : "图片处理失败，换一张试试");
        setPhase("cropping");
      }
    },
    [picked]
  );

  const lines = ask?.lines && ask.lines.length > 0 ? ask.lines : null;

  const recognize = useCallback(async () => {
    if (!sourceBlob && !typedText.trim()) return;
    setPhase("recognizing");
    setError(null);
    setRetryKind(null);
    try {
      const r = await askQuestion({
        image: sourceBlob,
        text: typedText,
        subject,
      });
      setAsk(r);
      setConfirmText(r.text ?? "");
      setSolve(null);
      setFeedback(null);
      setWrongbookAdded(false);
      setChat([]);
      setShowSteps(false);
      setShowAnswer(false);
      // 有分行 + 有图 → 先让学生点行；否则直接进确认。
      setPhase(r.lines && r.lines.length > 0 && r.has_image ? "lines" : "confirm");
    } catch (e) {
      setError(e instanceof Error ? e.message : "识别失败，请重试");
      setRetryKind("recognize");
      setPhase("idle");
    }
  }, [sourceBlob, typedText, subject]);

  const startSolve = useCallback(async (questionIndex?: number) => {
    if (!ask) return;
    setPhase("solving");
    setError(null);
    setRetryKind(null);
    setShowSteps(false);
    setShowAnswer(false);
    try {
      const r = await solveAsk(ask.ask_id, {
        text: confirmText.trim(),
        subject: ask.subject ?? subject,
        grade: ask.grade,
        ...(typeof questionIndex === "number" ? { question_index: questionIndex } : {}),
      });
      setSolve(r);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "解题失败，请重试");
      setRetryKind("solve");
      setPhase("confirm");
    }
  }, [ask, confirmText, subject]);

  const retry = useCallback(() => {
    if (retryKind === "solve") void startSolve();
    else void recognize();
  }, [retryKind, startSolve, recognize]);

  const markUnderstood = useCallback(async () => {
    if (!ask) return;
    setFeedback("understood");
    try {
      await askFeedback(ask.ask_id, true);
    } catch {
      /* 记录失败不打断体验：界面已给出"已记录"反馈 */
    }
  }, [ask]);

  const markNotUnderstood = useCallback(async () => {
    if (!ask) return;
    setFeedback("not_understood");
    try {
      await askFeedback(ask.ask_id, false);
    } catch {
      /* 同上 */
    }
  }, [ask]);

  const addWrongbook = useCallback(async () => {
    if (!ask) return;
    setWrongbookBusy(true);
    setError(null);
    try {
      await addToWrongbook(ask.record_id);
      setWrongbookAdded(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加入错题本失败");
    } finally {
      setWrongbookBusy(false);
    }
  }, [ask]);

  const sendChat = useCallback(async () => {
    const msg = chatInput.trim();
    if (!ask || !msg) return;
    setChat((c) => [...c, { role: "me", text: msg }]);
    setChatInput("");
    setChatBusy(true);
    try {
      const r = await askFollowup(ask.ask_id, msg);
      setChat((c) => [
        ...c,
        {
          role: "ai",
          text:
            r.status === "llm_unavailable" && !r.reply
              ? "我们换个角度再看一遍步骤，哪一步不懂就回复“第几步”。"
              : r.reply,
        },
      ]);
    } catch (e) {
      setChat((c) => [
        ...c,
        { role: "ai", text: e instanceof Error ? e.message : "AI 老师有点忙，稍后再试" },
      ]);
    } finally {
      setChatBusy(false);
    }
  }, [ask, chatInput]);

  const reset = useCallback(() => {
    setPhase("idle");
    setPicked((prev) => {
      if (prev) URL.revokeObjectURL(prev.url);
      return null;
    });
    setSourceBlob(null);
    setTypedText("");
    setShowTyped(false);
    setAsk(null);
    setConfirmText("");
    setSolve(null);
    setFeedback(null);
    setWrongbookAdded(false);
    setChat([]);
    setChatInput("");
    setError(null);
    setRetryKind(null);
  }, []);

  const solver = solve ? solverLabel(solve.solver) : null;
  const kernel = kernelLabel(solve?.kernel);
  const solveX = solve as AskSolveExtra | null;
  const llmBusy = solve?.status === "llm_unavailable";
  const emptyText = phase === "confirm" && !confirmText.trim();
  const hasCard = !!solve?.card;

  return (
    <main className="mx-auto max-w-xl p-4 pb-28 space-y-4" data-testid="ask-root">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">拍照问题目</h1>
        <p className="text-base text-[var(--muted-foreground,#666)]">
          拍下不会的题，马上给你思路、步骤和答案。
        </p>
      </header>
      <ProductNav />

      {/* 裁剪：拍完先裁，去掉旁边的杂物/半张别的题 */}
      {phase === "cropping" && picked && (
        <CropBox
          src={picked.url}
          naturalWidth={picked.width}
          naturalHeight={picked.height}
          onCancel={reset}
          onConfirm={(crop) => void applyCrop(crop)}
        />
      )}

      {/* a. 选图 / 直接输入 */}
      {(phase === "idle" || phase === "recognizing") && (
        <>
          <CameraButton
            busy={phase === "recognizing"}
            onPick={(f) => void pickFile(f)}
            onType={() => setShowTyped(true)}
          />

          {showTyped && (
            <textarea
              data-testid="ask-text"
              className="w-full min-h-[120px] rounded-xl border p-3 text-base"
              placeholder="把题目打在这里，比如：求 x^2-4=0 的解"
              value={typedText}
              onChange={(e) => setTypedText(e.target.value)}
            />
          )}

          {sourceBlob && (
            <div className="flex items-center gap-2 rounded-xl border p-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={picked?.url}
                alt="题目预览"
                className="h-20 w-20 shrink-0 rounded-lg border object-contain"
                style={{ height: 80, width: 80, maxWidth: 80 }}
              />
              <div className="min-w-0 flex-1 text-sm text-[var(--muted-foreground,#888)]">
                已裁剪好，可以识别了
              </div>
              <OButton variant="ghost" className="min-h-[44px]" onClick={reset}>
                换一张
              </OButton>
            </div>
          )}

          <div className="space-y-2">
            <div className="text-sm text-[var(--muted-foreground,#888)]">科目（可不选）</div>
            <div className="flex flex-wrap gap-2">
              {SUBJECTS.map((s) => {
                const active = subject === s;
                return (
                  <button
                    key={s}
                    type="button"
                    aria-pressed={active}
                    className={`min-h-[44px] rounded-full border px-4 text-base ${
                      active
                        ? "bg-[var(--primary)] text-[var(--primary-foreground)] border-transparent"
                        : "bg-[var(--background)] border-[var(--border)]"
                    }`}
                    onClick={() => setSubject(active ? null : s)}
                  >
                    {s}
                  </button>
                );
              })}
            </div>
          </div>

          {phase === "recognizing" && (
            <WaitSkeleton title="正在识别题目…" seconds={elapsed} />
          )}

          <OButton
            size="lg"
            className="w-full min-h-[52px] text-base"
            data-testid="ask-recognize"
            loading={phase === "recognizing"}
            disabled={phase === "recognizing" || (!sourceBlob && !typedText.trim())}
            onClick={() => void recognize()}
          >
            识别题目
          </OButton>
        </>
      )}

      {/* b. 选行（有分行 + 有图时才出现）：图太大点不准就用下面的芯片 */}
      {phase === "lines" && ask && lines && picked && (
        <LineTapper
          imageUrl={picked.url}
          lines={lines}
          onChange={setConfirmText}
          onDone={() => setPhase("confirm")}
        />
      )}

      {/* c. 确认题目 */}
      {(phase === "confirm" || phase === "solving") && ask && (
        <OCard>
          <OCardHeader>
            <OCardTitle>确认题目（可以修改）</OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-3">
            {emptyText && (
              <div className="rounded-lg bg-[var(--alert-warn-bg,#fff7e6)] p-3 text-base text-[var(--alert-warn-fg,#8a5a00)]">
                没看清，请手动输入题目
              </div>
            )}
            {ask.warning && !emptyText && (
              <div className="text-sm text-[var(--muted-foreground,#888)]">{ask.warning}</div>
            )}
            <MathKeyboard target={confirmRef} onChange={setConfirmText} />
            <textarea
              ref={confirmRef}
              data-testid="ask-confirm-text"
              className="w-full min-h-[120px] rounded-xl border p-3 text-base"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
            />
            <OButton
              size="lg"
              className="w-full min-h-[52px] text-base"
              data-testid="ask-solve"
              loading={phase === "solving"}
              disabled={phase === "solving" || !confirmText.trim()}
              onClick={() => void startSolve()}
            >
              开始解题
            </OButton>
            {phase === "solving" && (
              <WaitSkeleton title="正在解题…" seconds={elapsed} hintAfterSeconds={6} />
            )}
          </div>
        </OCard>
      )}

      {/* d. 结果 */}
      {phase === "done" && solve && (
        <OCard>
          <OCardHeader>
            <OCardTitle>
              <span className="flex items-center gap-2">
                解题结果
                {solve.subject && subjectLabel(solve.subject) && (
                  <span
                    className="rounded-full bg-[var(--muted,#eee)] px-2 py-0.5 text-xs text-[var(--muted-foreground,#666)]"
                    data-testid="ask-subject-chip"
                  >
                    {subjectLabel(solve.subject)}
                  </span>
                )}
                {solver && (
                  <span className="rounded-full bg-[var(--secondary)] px-2 py-0.5 text-xs text-[var(--secondary-foreground)]">
                    {solver}
                  </span>
                )}
                {kernel && solver === "精确求解" && (
                  <span className="rounded-full bg-[var(--muted,#eee)] px-2 py-0.5 text-xs text-[var(--muted-foreground,#666)]">
                    {kernel}
                  </span>
                )}
              </span>
            </OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-4">
            {llmBusy && (
              <div className="space-y-2 rounded-lg bg-[var(--alert-warn-bg,#fff7e6)] p-3 text-base text-[var(--alert-warn-fg,#8a5a00)]">
                <div>AI 老师有点忙，稍后再试</div>
                <OButton variant="outline" className="min-h-[44px]" onClick={() => void startSolve()}>
                  重试
                </OButton>
              </div>
            )}

            {/* 卡片型答案（单词/古诗/拼音/成语）：比 hint/steps 更贴题型 */}
            <AnswerCard card={solve.card} />

            
            {solve.status === "multi" && (solveX?.questions?.length ?? 0) > 0 && (
              <div className="space-y-2" data-testid="ask-multi">
                {solveX?.questions?.map((q) => (
                  <button
                    key={q.index}
                    type="button"
                    className="w-full rounded-lg border p-3 text-left text-base min-h-[44px]"
                    onClick={() => void startSolve(q.index)}
                  >
                    <span className="mr-2 font-semibold">{q.label}</span>
                    <MathText text={q.text} />
                    {q.solvable && (
                      <span className="ml-2 rounded-full bg-[var(--secondary)] px-2 py-0.5 text-xs">可精确求解</span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {!hasCard && solve.hint && (
              <div
                className="rounded-xl bg-[var(--secondary)] p-4 text-base"
                data-testid="ask-hint"
              >
                <div className="mb-1 text-sm font-semibold">提示</div>
                <MathText text={solve.hint} />
              </div>
            )}

            {solve.steps.length > 0 && !hasCard && (
              <div data-testid="ask-steps">
                {showSteps ? (
                  <ol className="space-y-2 text-base">
                    {solve.steps.map((s, i) => (
                      <li key={i} className="rounded-lg border p-3">
                        <span className="mr-2 text-sm text-[var(--muted-foreground,#888)]">
                          {i + 1}
                        </span>
                        <MathText text={s} />
                      </li>
                    ))}
                  </ol>
                ) : (
                  <OButton
                    variant="outline"
                    className="w-full min-h-[44px]"
                    onClick={() => setShowSteps(true)}
                  >
                    看完整步骤
                  </OButton>
                )}
              </div>
            )}

            {solve.answer != null && solve.answer !== "" && !hasCard && (
              <div>
                {showAnswer ? (
                  <div className="rounded-xl border p-4 text-base">
                    <div className="mb-1 text-sm font-semibold">答案</div>
                    <MathText text={solve.answer} />
                  </div>
                ) : (
                  <OButton
                    variant="outline"
                    className="w-full min-h-[44px]"
                    onClick={() => setShowAnswer(true)}
                  >
                    看答案
                  </OButton>
                )}
              </div>
            )}

            {solve.explanation && (
              <div className="text-base whitespace-pre-wrap text-[var(--muted-foreground,#555)]">
                {solve.explanation}
              </div>
            )}

            {solve.status === "no_exact_solver" && (solveX?.similar?.length ?? 0) > 0 && (
              <div className="space-y-2" data-testid="ask-similar">
                <div className="text-sm font-semibold">同类题参考</div>
                {solveX?.similar?.map((q, i) => (
                  <details key={i} className="rounded-lg border p-3 text-base">
                    <summary className="cursor-pointer"><MathText text={q.text} /></summary>
                    {(q.steps ?? []).length > 0 && (
                      <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
                        {(q.steps ?? []).map((st, j) => (
                          <li key={j}><MathText text={st} /></li>
                        ))}
                      </ol>
                    )}
                    <div className="mt-2 text-sm">答案：<MathText text={q.answer} /></div>
                  </details>
                ))}
              </div>
            )}

            {solve.status === "no_exact_solver" && (solveX?.references?.length ?? 0) > 0 && (
              <div className="space-y-2" data-testid="ask-references">
                <div className="text-sm font-semibold">教材相关内容</div>
                {solveX?.references?.map((r, i) => (
                  <div key={i} className="rounded-lg bg-[var(--muted,#f4f4f4)] p-3 text-sm">
                    {r.book_name && <div className="mb-1 text-xs text-[var(--muted-foreground,#888)]">{r.book_name}{r.page_number ? ` 第 ${r.page_number} 页` : ""}</div>}
                    {r.content}
                  </div>
                ))}
              </div>
            )}

            {solve.status === "partial" && (
              <div className="text-sm text-[var(--muted-foreground,#888)]">
                这道题只讲了一部分，可以再问问我。
              </div>
            )}

            {feedback === "understood" && (
              <div className="text-base text-[var(--success,#0a0)]">太棒了，已记录 🎉</div>
            )}

            {feedback === "not_understood" && (
              <div className="space-y-3">
                <div className="text-base">没关系，接着问，我慢慢讲。</div>
                {chat.length > 0 && (
                  <ul className="space-y-2">
                    {chat.map((m, i) => (
                      <li
                        key={i}
                        className={`rounded-lg p-3 text-base ${
                          m.role === "me"
                            ? "bg-[var(--secondary)] ml-6"
                            : "bg-[var(--muted,#f4f4f4)] mr-6"
                        }`}
                      >
                        {m.text}
                      </li>
                    ))}
                  </ul>
                )}
                <div className="flex gap-2">
                  <input
                    className="min-h-[44px] flex-1 rounded-xl border px-3 text-base"
                    placeholder="哪里没懂？问问我"
                    value={chatInput}
                    onChange={(e) => setChatInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") void sendChat();
                    }}
                  />
                  <OButton
                    className="min-h-[44px]"
                    loading={chatBusy}
                    disabled={chatBusy || !chatInput.trim()}
                    onClick={() => void sendChat()}
                  >
                    发送
                  </OButton>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between gap-2">
              <ReportWrong askId={solve.ask_id} />
              <button
                type="button"
                className="text-base text-[var(--primary)] underline underline-offset-4"
                onClick={reset}
              >
                再拍一道
              </button>
            </div>
          </div>
        </OCard>
      )}

      {error && (
        <OCard>
          <div className="p-4 space-y-3 text-base text-[var(--destructive,#c00)]">
            <div>{error}</div>
            {retryKind && (
              <OButton variant="outline" className="min-h-[44px]" onClick={retry}>
                重试
              </OButton>
            )}
          </div>
        </OCard>
      )}

      {/* e. 底部动作栏 */}
      {phase === "done" && solve?.status !== "multi" && (
        <div className="fixed inset-x-0 bottom-0 z-10 border-t bg-[var(--background)] p-3">
          <div className="mx-auto flex max-w-xl gap-2">
            <OButton
              className="flex-1 min-h-[48px] text-base"
              data-testid="ask-understood"
              onClick={() => void markUnderstood()}
            >
              懂了
            </OButton>
            <OButton
              variant="outline"
              className="flex-1 min-h-[48px] text-base"
              data-testid="ask-not-understood"
              onClick={() => void markNotUnderstood()}
            >
              没懂
            </OButton>
            <OButton
              variant="outline"
              className="flex-1 min-h-[48px] text-base"
              data-testid="ask-add-wrongbook"
              loading={wrongbookBusy}
              disabled={wrongbookBusy || wrongbookAdded}
              onClick={() => void addWrongbook()}
            >
              {wrongbookAdded ? "已加入错题本 ✓" : "加入错题本"}
            </OButton>
          </div>
        </div>
      )}
    </main>
  );
}
