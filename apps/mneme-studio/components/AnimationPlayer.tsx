"use client";

// AnimationPlayer —— 播放 POST /v1/animate 返回的确定性时间线（mneme.anim/1）。
//
// 时间线是纯数据（白名单图元 + 关键帧），由服务端确定性内核编排；这里只把它嵌进一个
// sandbox="allow-scripts" 的 iframe（opaque origin，拿不到本页 localStorage 里的 token），
// iframe 里只加载自托管的 /v1/edu-assets 资源（KaTeX + mneme-animator-1 播放器），
// CSP 把脚本/样式/字体都钉死在这个前缀上——没有外部 CDN，也没有任何代码来自时间线本身。

import { useMemo } from "react";
import { eduAssetBase, type AnimSpec } from "@/lib/mcp";

function escapeJsonForHtml(spec: AnimSpec): string {
  return JSON.stringify(spec)
    .replace(/</g, "\\u003c")
    .replace(/>/g, "\\u003e")
    .replace(/&/g, "\\u0026")
    .replace(/\u2028/g, "\\u2028")
    .replace(/\u2029/g, "\\u2029");
}

function escapeAttr(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");
}

export function buildAnimationSrcDoc(spec: AnimSpec, assetBase: string): string {
  const a = escapeAttr(assetBase);
  const csp = [
    "default-src 'none'",
    `script-src ${a}/`,
    `style-src ${a}/ 'unsafe-inline'`,
    `font-src ${a}/`,
    "img-src data:",
    "connect-src 'none'",
    "form-action 'none'",
    "base-uri 'none'",
  ].join("; ");
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="${csp}">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="stylesheet" href="${a}/katex-0.16.8/katex.min.css">
<link rel="stylesheet" href="${a}/mneme-animator-1/player.css">
<script src="${a}/katex-0.16.8/katex.min.js"></script>
<script src="${a}/katex-0.16.8/contrib/auto-render.min.js"></script>
</head><body><div id="anim-root"></div>
<script id="anim-spec" type="application/json">${escapeJsonForHtml(spec)}</script>
<script src="${a}/mneme-animator-1/player.js"></script>
</body></html>`;
}

export function AnimationPlayer({ spec, height = 820 }: { spec: AnimSpec; height?: number }) {
  const srcDoc = useMemo(() => buildAnimationSrcDoc(spec, eduAssetBase()), [spec]);
  return (
    <iframe
      data-testid="anim-frame"
      title={`步骤动画：${spec.title}`}
      className="w-full rounded-lg border-0"
      style={{ height }}
      sandbox="allow-scripts"
      srcDoc={srcDoc}
    />
  );
}
