# BUG: `@helios/blocks` `OMarkdownRenderer` 在 Next 16 / React 19 下崩溃（`runSync finished async`）

**报告方**：mneme（W2b S1 mneme-studio）
**严重度**：**阻断（不是挂起）** —— 数学公式渲染是 Mneme 刚需（数学是主线科目），此 bug 阻塞学习 UI 的长期形态。
**包**：`@helios/blocks` 4.6.0
**组件**：`OMarkdownRenderer`
**环境**：Next.js **16.2.10**（Turbopack）+ React **19.2.4** + TypeScript 5，App Router，client component。

## 症状
在一个 `"use client"` 组件里渲染 `<OMarkdownRenderer content="解 x^2-5x+6=0" math />`：
- 浏览器抛未捕获错误 → **`PAGEERROR: \`runSync\` finished async. Use \`run\` instead`**。
- 该错误发生在 render/hydration 期，**整页客户端 hydration 崩溃** —— 页面只剩服务端 RSC flight 载荷（`self.__next_f.push(...)`），交互全失效。

## 复现（最小）
```tsx
"use client";
import { OMarkdownRenderer } from "@helios/blocks";
export default function P() {
  return <OMarkdownRenderer content="解 x^2-5x+6=0" math />;
}
```
Next 16 + React 19，`next build && next start`，浏览器打开该页 → 崩。
（对照：同环境下 OButton / OTextInput / OCard / OProgress / OEmptyState 均正常，仅 OMarkdownRenderer 崩。）

## 根因假设
错误串 `runSync finished async. Use run instead` 是 **unified** 生态（remark/rehype）的典型报错：
调用了同步 `processor.runSync()` / `processSync()`，但管线里有一个**异步** transformer/plugin 返回了 Promise，
unified 检测到"sync 调用却异步完成"即抛此错。

OMarkdownRenderer 很可能在 `math`（KaTeX）或默认插件链启用时挂了**异步插件**，却仍走 `runSync` 同步路径。
React 19 / Next 16 的渲染时序（并发/严格模式）可能放大了这一时序问题。

## 影响
- `math` 渲染不可用 → 数学题干（LaTeX/公式）无法呈现。**Mneme 主线是数学**，学习 UI 必须渲染公式，故此 bug 阻塞 W2b 学习面的长期形态。
- 连带：整页 hydration 崩溃（不只是降级），任何含 OMarkdownRenderer 的页面不可用。

## mneme 侧临时规避（非解决）
mneme-studio 的 `/learn` 暂用**纯文本**渲染 prompt（`<div>{prompt}</div>`），绕开 OMarkdownRenderer。
代价：无公式排版。数学渲染待 blocks 修复后接回。

## 请 blocks org 处置
1. OMarkdownRenderer 在启用 `math`（及任何异步插件如 `highlight`/shiki）时，改用 unified **异步 `run()` / `process()`**，而非 `runSync()`；组件内部以 state + effect 承接异步结果（或走 RSC 异步渲染）。
2. 或：为 `math` 选用**同步** KaTeX 管线（rehype-katex 通常可同步），确保 runSync 路径下无异步 plugin。
3. 附 Next 16 / React 19 兼容性回归用例（当前测试矩阵疑未覆盖此组合）。

修复后 mneme 接回 OMarkdownRenderer 渲染数学题干。
