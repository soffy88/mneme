"use client";

// /studio/ask —— 拍照问题目（移动端优先，单屏分步）。
//
// 数据通道是 lib/questions.ts（/v1/questions/*）。前端只上传图片/文字、展示内核与
// LLM 的返回；不判分、不生成答案。图片在**客户端**旋转 + 缩放到长边 1600 再上传，
// 取原图时带 token 换 blob → object URL（token 绝不进 URL）。

import { useCallback, useEffect, useRef, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { MathText } from "@/components/MathText";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  askFollowup, askFeedback, askQuestion, addToWrongbook, solveAsk,
  type AskResult, type AskSolveResult,
} from "@/lib/questions";

const SUBJECTS = ["数学", "物理", "化学", "英语", "语文", "其他"];
const MAX_SIDE = 1600;

/** 客户端图片处理：旋转 rotationDeg 度 + 缩放到长边 ≤1600 + JPEG q=0.85。 */
async function processImage(source: Blob, rotationDeg: number): Promise<Blob> {
  const url = URL.createObjectURL(source);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("图片读取失败，换一张试试"));
      el.src = url;
    });
    const srcW = img.naturalWidth;
    const srcH = img.naturalHeight;
    if (!srcW || !srcH) throw new Error("图片读取失败，换一张试试");

    const swap = rotationDeg % 180 !== 0;
    const outW = swap ? srcH : srcW;
    const outH = swap ? srcW : srcH;
    const scale = Math.min(1, MAX_SIDE / Math.max(outW, outH));
    const cw = Math.max(1, Math.round(outW * scale));
    const ch = Math.max(1, Math.round(outH * scale));

    const canvas = document.createElement("canvas");
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("这个浏览器处理不了图片");
    ctx.translate(cw / 2, ch / 2);
    ctx.rotate((rotationDeg * Math.PI) / 180);
    ctx.drawImage(img, (-srcW * scale) / 2, (-srcH * scale) / 2, srcW * scale, srcH * scale);

    const out = await new Promise<Blob | null>((resolve) =>
      canvas.toBlob((b) => resolve(b), "image/jpeg", 0.85)
    );
    if (!out) throw new Error("图片处理失败，换一张试试");
    return out;
  } finally {
    URL.revokeObjectURL(url);
  }
}

type Phase = "idle" | "recognizing" | "confirm" | "solving" | "done";
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

function solverLabel(solver: AskSolveResult["solver"]): string | null {
  if (solver === "kernel") return "精确求解";
  if (solver === "llm") return "AI 讲解";
  return null;
}

export default function AskPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [subject, setSubject] = useState<string | null>(null);

  const [sourceBlob, setSourceBlob] = useState<Blob | null>(null);
  const [rotation, setRotation] = useState(0);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [showTyped, setShowTyped] = useState(false);
  const [typedText, setTypedText] = useState("");

  const [ask, setAsk] = useState<AskResult | null>(null);
  const [confirmText, setConfirmText] = useState("");
  const [solve, setSolve] = useState<AskSolveResult | null>(null);

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

  const cameraRef = useRef<HTMLInputElement>(null);
  const albumRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!getToken()) redirectToLogin();
  }, []);

  // 预览 URL 生命周期：换了就回收旧的。
  useEffect(() => {
    if (!sourceBlob) {
      setPreviewUrl(null);
      return;
    }
    const url = URL.createObjectURL(sourceBlob);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [sourceBlob]);

  // 解题计时器（"正在思考… 12s"）。
  useEffect(() => {
    if (phase !== "solving") return;
    setElapsed(0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [phase]);

  const pickFile = useCallback(async (file: File | null) => {
    if (!file) return;
    setError(null);
    setRetryKind(null);
    try {
      const blob = await processImage(file, 0);
      setRotation(0);
      setSourceBlob(blob);
    } catch (e) {
      setError(e instanceof Error ? e.message : "图片处理失败");
    }
  }, []);

  const rotate = useCallback(async () => {
    if (!sourceBlob) return;
    setError(null);
    try {
      const next = (rotation + 90) % 360;
      const blob = await processImage(sourceBlob, 90);
      setRotation(next);
      setSourceBlob(blob);
    } catch (e) {
      setError(e instanceof Error ? e.message : "旋转失败");
    }
  }, [sourceBlob, rotation]);

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
      setPhase("confirm");
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
      } as Parameters<typeof solveAsk>[1]);
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
    setSourceBlob(null);
    setRotation(0);
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
    if (cameraRef.current) cameraRef.current.value = "";
    if (albumRef.current) albumRef.current.value = "";
  }, []);

  const solver = solve ? solverLabel(solve.solver) : null;
  const solveX = solve as AskSolveExtra | null;
  const llmBusy = solve?.status === "llm_unavailable";
  const emptyText = phase === "confirm" && !confirmText.trim();

  return (
    <main className="mx-auto max-w-xl p-4 pb-28 space-y-4" data-testid="ask-root">
      <header className="space-y-1">
        <h1 className="text-2xl font-bold">拍照问题目</h1>
        <p className="text-base text-[var(--muted-foreground,#666)]">
          拍下不会的题，AI 老师一步步讲给你听。
        </p>
      </header>
      <ProductNav />

      {/* a. 选图 / 直接输入 */}
      {(phase === "idle" || phase === "recognizing") && (
        <>
          <div className="grid grid-cols-2 gap-3">
            <OButton
              variant="outline"
              className="h-24 flex-col gap-1 text-base"
              data-testid="ask-camera"
              disabled={phase === "recognizing"}
              onClick={() => cameraRef.current?.click()}
            >
              <span className="text-2xl" aria-hidden>📷</span>
              拍照
            </OButton>
            <OButton
              variant="outline"
              className="h-24 flex-col gap-1 text-base"
              disabled={phase === "recognizing"}
              onClick={() => albumRef.current?.click()}
            >
              <span className="text-2xl" aria-hidden>🖼️</span>
              相册
            </OButton>
          </div>
          <input
            ref={cameraRef}
            type="file"
            accept="image/*"
            capture="environment"
            className="hidden"
            onChange={(e) => void pickFile(e.target.files?.[0] ?? null)}
          />
          <input
            ref={albumRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={(e) => void pickFile(e.target.files?.[0] ?? null)}
          />

          {!showTyped ? (
            <button
              type="button"
              className="text-base text-[var(--primary)] underline underline-offset-4"
              onClick={() => setShowTyped(true)}
            >
              或者直接输入题目
            </button>
          ) : (
            <textarea
              data-testid="ask-text"
              className="w-full min-h-[120px] rounded-xl border p-3 text-base"
              placeholder="把题目打在这里，比如：求 x^2-4=0 的解"
              value={typedText}
              onChange={(e) => setTypedText(e.target.value)}
            />
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

          {previewUrl && (
            <OCard>
              <div className="p-3 space-y-3">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={previewUrl}
                  alt="题目预览"
                  className="mx-auto max-h-64 w-auto rounded-lg border object-contain"
                />
                <div className="flex gap-2">
                  <OButton
                    variant="ghost"
                    className="min-h-[44px]"
                    onClick={() => void rotate()}
                  >
                    ↻ 旋转
                  </OButton>
                  <OButton variant="ghost" className="min-h-[44px]" onClick={reset}>
                    换一张
                  </OButton>
                </div>
              </div>
            </OCard>
          )}

          <OButton
            size="lg"
            className="w-full min-h-[52px] text-base"
            data-testid="ask-recognize"
            loading={phase === "recognizing"}
            disabled={phase === "recognizing" || (!sourceBlob && !typedText.trim())}
            onClick={() => void recognize()}
          >
            {phase === "recognizing" ? "正在识别…" : "识别题目"}
          </OButton>
        </>
      )}

      {/* b/c. 确认题目 */}
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
            <textarea
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
              {phase === "solving" ? "正在思考…" : "开始解题"}
            </OButton>
            {phase === "solving" && (
              <div className="text-center text-sm text-[var(--muted-foreground,#888)]">
                正在思考… {elapsed} 秒
              </div>
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
                {solver && (
                  <span className="rounded-full bg-[var(--secondary)] px-2 py-0.5 text-xs text-[var(--secondary-foreground)]">
                    {solver}
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

            {solve.hint && (
              <div
                className="rounded-xl bg-[var(--secondary)] p-4 text-base"
                data-testid="ask-hint"
              >
                <div className="mb-1 text-sm font-semibold">提示</div>
                <MathText text={solve.hint} />
              </div>
            )}

            {solve.steps.length > 0 && (
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

            {solve.answer != null && solve.answer !== "" && (
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

            <button
              type="button"
              className="text-base text-[var(--primary)] underline underline-offset-4"
              onClick={reset}
            >
              再拍一道
            </button>
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
      {phase === "done" && (
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
