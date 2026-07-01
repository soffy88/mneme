import { useMemo } from "react"
import katex from "katex"

/**
 * 渲染含 LaTeX 的文本：$$...$$ 独立公式、$...$ 行内公式，其余按纯文本。
 * 用于 rich_content / 讲解内容里的数学公式。
 */
function renderMath(tex: string, display: boolean): string {
  try {
    return katex.renderToString(tex, { throwOnError: false, displayMode: display })
  } catch {
    return escapeHtml(display ? `$$${tex}$$` : `$${tex}$`)
  }
}

function escapeHtml(s: string): string {
  return s.replace(/[<>&]/g, c => (c === "<" ? "&lt;" : c === ">" ? "&gt;" : "&amp;"))
}

export function MathText({ children, className }: { children: string; className?: string }) {
  const html = useMemo(() => {
    const src = children ?? ""
    let out = ""
    let i = 0
    while (i < src.length) {
      if (src.startsWith("$$", i)) {
        const end = src.indexOf("$$", i + 2)
        if (end !== -1) { out += renderMath(src.slice(i + 2, end), true); i = end + 2; continue }
      }
      if (src[i] === "$") {
        const end = src.indexOf("$", i + 1)
        if (end !== -1) { out += renderMath(src.slice(i + 1, end), false); i = end + 1; continue }
      }
      out += escapeHtml(src[i])
      i++
    }
    return out
  }, [children])

  return <span className={className} dangerouslySetInnerHTML={{ __html: html }} />
}
