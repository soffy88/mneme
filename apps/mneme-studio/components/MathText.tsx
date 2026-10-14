"use client";

// MathText —— 把题干里的 LaTeX（$...$ 行内、$$...$$ 显示）用 KaTeX 渲染，其余当纯文本。
// 数学是 Mneme 刚需；@helios/blocks 的 OMarkdownRenderer 在 Next16/React19 下 runSync 崩，
// 故直接用 katex（纯 JS，无 React 版本耦合）。throwOnError:false → 坏 LaTeX 不崩、回退原文。

import katex from "katex";
import "katex/dist/katex.min.css";

type Seg = { t: "text" | "inline" | "display"; v: string };

/** 题库里的填空占位（\$ \qquad \$、$\qquad$、\underline{\quad}）→（　　）；转义的 \$ 还原。 */
export function normalizeBlanks(s: string): string {
  return s
    .replace(/\\?\$\s*(?:\\underline\{[^}]*\}|\\q?quad|\\_+|_+)\s*\\?\$/g, "（　　）")
    .replace(/\\\$/g, "$")
    .replace(/<ImageHere>/g, "");
}

/** 纯文本段（内核步骤）里的 x^2、sqrt(3) → x²、√(3)，学生更好读。 */
export function prettyMath(s: string): string {
  return s
    .replace(/\^2(?![\d.])/g, "²")
    .replace(/\^3(?![\d.])/g, "³")
    .replace(/sqrt\(/g, "√(");
}

function tokenize(raw: string): Seg[] {
  const s = normalizeBlanks(raw);
  const out: Seg[] = [];
  let i = 0;
  while (i < s.length) {
    if (s.startsWith("$$", i)) {
      const end = s.indexOf("$$", i + 2);
      if (end < 0) {
        out.push({ t: "text", v: s.slice(i) });
        break;
      }
      out.push({ t: "display", v: s.slice(i + 2, end) });
      i = end + 2;
    } else if (s[i] === "$") {
      const end = s.indexOf("$", i + 1);
      if (end < 0) {
        out.push({ t: "text", v: s.slice(i) });
        break;
      }
      out.push({ t: "inline", v: s.slice(i + 1, end) });
      i = end + 1;
    } else {
      let j = s.indexOf("$", i);
      if (j < 0) j = s.length;
      out.push({ t: "text", v: s.slice(i, j) });
      i = j;
    }
  }
  return out;
}

function render(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, { throwOnError: false, displayMode: display });
  } catch {
    return tex; // 兜底：渲染异常时显示原始 LaTeX，绝不崩页
  }
}

export function MathText({ text }: { text: string }) {
  const segs = tokenize(text ?? "");
  return (
    <span className="whitespace-pre-wrap">
      {segs.map((p, idx) =>
        p.t === "text" ? (
          <span key={idx}>{prettyMath(p.v)}</span>
        ) : (
          <span
            key={idx}
            // KaTeX 输出为其自有标记；throwOnError:false 已处理非法输入
            dangerouslySetInnerHTML={{ __html: render(p.v, p.t === "display") }}
          />
        )
      )}
    </span>
  );
}
