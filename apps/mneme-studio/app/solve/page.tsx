"use client";

// /studio/solve —— W4 Solve 模式：自然语言题目 -> 内核真实求解 + LLM 讲解。
//
// FC-5：零 DB，唯一数据通道是 mcp.solveProblem()。原有页面零改动，本页是
// 新增独立路由。
//
// answer/steps 是 7 个确定性内核（S0 加固后全经沙箱）的真实输出；narration
// 是 LLM 纯附加的自然语言讲解——本页把两者渲染成并列的、来源不同的区块
// （"内核求解" vs "讲解"），不把 narration 混进 answer/steps 里，呈现层上
// 也体现 SV-2/SV-4 这条红线：求解来自内核，讲解只是转述，不是另一个答案来源。

import { useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { mcp, getToken, redirectToLogin, type SolveProblemResult } from "@/lib/mcp";

export default function SolvePage() {
  const [problemText, setProblemText] = useState("");
  const [result, setResult] = useState<SolveProblemResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit() {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    const text = problemText.trim();
    if (!text) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const r = await mcp.solveProblem(text);
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="solve-root">
      <h1 className="text-2xl font-bold">善学记 · 解题</h1>
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        输入一道数学题，系统用确定性内核真实求解，再配一段讲解帮你理解每一步。
      </p>

      <OCard>
        <div className="p-4 space-y-3">
          <textarea
            data-testid="problem-input"
            className="w-full rounded-lg border p-3 text-sm"
            rows={3}
            placeholder="例如：求 x^2-4=0 的解"
            value={problemText}
            onChange={(e) => setProblemText(e.target.value)}
          />
          <OButton
            data-testid="submit-problem"
            disabled={loading || !problemText.trim()}
            onClick={() => void handleSubmit()}
          >
            {loading ? "求解中…" : "求解"}
          </OButton>
        </div>
      </OCard>

      {error && (
        <OCard>
          <div
            className="p-4 text-sm text-[var(--o-color-danger,#c00)]"
            data-testid="solve-error"
          >
            出错了：{error}
          </div>
        </OCard>
      )}

      {result && !result.solvable && (
        <OEmptyState
          title="这道题暂时求解不了"
          description={result.error || "未知原因"}
        />
      )}

      {result && result.solvable && (
        <div className="space-y-4" data-testid="solve-result">
          {result.restated_problem && (
            <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
              题意理解：{result.restated_problem}
            </p>
          )}

          <OCard data-testid="kernel-answer">
            <OCardHeader>
              <OCardTitle>内核求解（确定性，非 LLM 生成）</OCardTitle>
            </OCardHeader>
            <div className="p-4 space-y-3">
              <div className="font-medium">答案：{result.answer}</div>
              <ol className="space-y-1 text-sm list-none">
                {result.steps.map((s) => (
                  <li key={s.step_number} data-testid="solve-step">
                    {s.step_number}. {s.description}：{s.expression} → {s.result}
                  </li>
                ))}
              </ol>
            </div>
          </OCard>

          {result.narration && (
            <OCard data-testid="narration">
              <OCardHeader>
                <OCardTitle>讲解（LLM 转述，仅供理解参考）</OCardTitle>
              </OCardHeader>
              <div className="p-4 text-sm whitespace-pre-wrap">
                {result.narration}
              </div>
            </OCard>
          )}
        </div>
      )}
    </main>
  );
}
