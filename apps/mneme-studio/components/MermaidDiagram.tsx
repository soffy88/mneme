"use client";

// MermaidDiagram —— W4 Visualize：客户端渲染 LLM 撰写的 mermaid 声明式
// 图示文本。securityLevel:"strict" 显式声明（mermaid 默认即 strict，这里
// 显式写出不依赖默认值——纵深防御，防止库版本升级改了默认值却没人注意）。
// mermaid.render() 本身只解析 mermaid 自己的图表 DSL 语法树再输出 SVG，
// 不 eval 任意 JS（VZ-3）。

import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";

let initialized = false;

function ensureInitialized() {
  if (initialized) return;
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict" });
  initialized = true;
}

export function MermaidDiagram({ source }: { source: string }) {
  const id = useId().replace(/:/g, "-");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    ensureInitialized();
    let cancelled = false;
    void (async () => {
      try {
        const result = await mermaid.render(`mermaid-${id}`, source);
        if (!cancelled) setSvg(result.svg);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, source]);

  if (error) {
    return (
      <div className="text-sm text-[var(--o-color-danger,#c00)]" data-testid="mermaid-error">
        图示渲染失败：{error}
      </div>
    );
  }
  if (!svg) {
    return <div data-testid="mermaid-loading">正在渲染图示…</div>;
  }
  return (
    <div
      data-testid="mermaid-diagram"
      // mermaid.render() 的输出是它自己生成的 SVG 字符串，不是原始 LLM
      // 文本——LLM 只提供了 DSL 源码，真正的 SVG 由 mermaid 库解析产出。
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  );
}
