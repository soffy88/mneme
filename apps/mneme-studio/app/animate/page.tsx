"use client";

// /studio/animate —— 步骤动画（DeepTutor Animator 对标，不用 Manim）。
//
// POST /v1/animate {kind, params} → 确定性内核（立体几何 / 圆锥曲线弦 / 化学配平 /
// visualize 函数图像）编排出的纯数据时间线；AnimationPlayer 在 sandbox iframe 里用自托管
// 播放器渲染（播放 / 暂停 / 单步）。服务端不执行任何 LLM 写的代码。
// 深链：/studio/animate?kind=conic_chord&params=<base64url(JSON)>（Lab 页的"动画"按钮用）。

import { useCallback, useEffect, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle } from "@helios/blocks";
import { AnimationPlayer } from "@/components/AnimationPlayer";
import { ProductNav } from "@/components/ProductNav";
import { ANIM_KIND_LABEL, ANIM_PRESETS } from "@/lib/animatePresets";
import { animate, getToken, redirectToLogin, type AnimKind, type AnimSpec } from "@/lib/mcp";

const KINDS: AnimKind[] = ["solid_geometry", "conic_chord", "equation_balance", "function_graph"];

function decodeAnimParams(s: string): unknown {
  const b64 = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(b64 + "===".slice((b64.length + 3) % 4));
  const bytes = Uint8Array.from(bin, (c) => c.charCodeAt(0));
  return JSON.parse(new TextDecoder().decode(bytes));
}

export default function AnimatePage() {
  const [kind, setKind] = useState<AnimKind>("conic_chord");
  const [paramsText, setParamsText] = useState(JSON.stringify(ANIM_PRESETS.conic_chord[0].params, null, 2));
  const [spec, setSpec] = useState<AnimSpec | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = useCallback(async (k: AnimKind, text: string) => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    let params: unknown;
    try {
      params = JSON.parse(text);
    } catch {
      setError("参数不是合法的 JSON");
      return;
    }
    setLoading(true);
    setError(null);
    setSpec(null);
    try {
      setSpec(await animate(k, params));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    const q = new URLSearchParams(window.location.search);
    const k = q.get("kind") as AnimKind | null;
    const p = q.get("params");
    if (k && KINDS.includes(k) && p) {
      try {
        const text = JSON.stringify(decodeAnimParams(p), null, 2);
        setKind(k);
        setParamsText(text);
        void run(k, text);
      } catch {
        setError("链接里的动画参数无法解析");
      }
    }
  }, [run]);

  function pickKind(k: AnimKind) {
    setKind(k);
    setParamsText(JSON.stringify(ANIM_PRESETS[k][0].params, null, 2));
    setSpec(null);
    setError(null);
  }

  return (
    <main className="mx-auto max-w-5xl p-6 space-y-4" data-testid="animate-root">
      <h1 className="text-2xl font-bold">善学记 · 步骤动画</h1>
      <ProductNav />
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        动画的每一帧都来自确定性内核的精确计算（不是 AI 画的），可以播放、暂停、一步一步看。
      </p>
      <div className="flex flex-wrap gap-2" role="tablist">
        {KINDS.map((k) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={kind === k}
            data-testid={`anim-kind-${k}`}
            className={`rounded-lg border px-3 py-1 text-sm ${kind === k ? "font-semibold bg-black/5" : ""}`}
            onClick={() => pickKind(k)}
          >
            {ANIM_KIND_LABEL[k]}
          </button>
        ))}
      </div>
      <OCard>
        <div className="p-4 space-y-3">
          <label className="block text-sm font-medium" htmlFor="anim-preset">
            例题
          </label>
          <select
            id="anim-preset"
            data-testid="anim-preset"
            className="w-full rounded-lg border p-2 text-sm"
            onChange={(e) => setParamsText(JSON.stringify(ANIM_PRESETS[kind][Number(e.target.value)].params, null, 2))}
          >
            {ANIM_PRESETS[kind].map((p, i) => (
              <option key={`${kind}-${i}`} value={i}>
                {p.label}
              </option>
            ))}
          </select>
          <details>
            <summary className="cursor-pointer text-sm">改参数</summary>
            <textarea
              data-testid="anim-params"
              className="mt-2 w-full rounded-lg border p-3 font-mono text-xs"
              rows={8}
              value={paramsText}
              onChange={(e) => setParamsText(e.target.value)}
            />
          </details>
          <OButton data-testid="anim-run" disabled={loading} onClick={() => void run(kind, paramsText)}>
            {loading ? "生成中…" : "生成步骤动画"}
          </OButton>
        </div>
      </OCard>
      {error && (
        <OCard>
          <div className="p-4 text-sm text-[var(--o-color-danger,#c00)]" data-testid="anim-error">
            出错了：{error}
          </div>
        </OCard>
      )}
      {spec && (
        <OCard data-testid="anim-result">
          <OCardHeader>
            <OCardTitle>
              {ANIM_KIND_LABEL[spec.kind]} · {spec.frames.length} 帧
              <span className="ml-2 text-xs font-normal text-[var(--o-color-fg-muted,#888)]">指纹 {spec.fingerprint}</span>
            </OCardTitle>
          </OCardHeader>
          <AnimationPlayer spec={spec} />
        </OCard>
      )}
    </main>
  );
}
