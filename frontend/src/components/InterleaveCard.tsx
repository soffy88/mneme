import { useEffect, useMemo, useState } from "react"
import { getReviewQueue, type ReviewQueueItem } from "../api"

/**
 * 交错复习池（M-B 机制可视化）：复习队列已被 interleave_select 排成"相邻题 KC 不同"，
 * 这里把序列摊开 + 标出相邻是否不同，让学生看见"为什么不让你连着刷同一类"。
 * 交错练习训练"认出该用哪招"（对抗惰性知识）。
 */
const PALETTE = [
  "bg-indigo-100 text-indigo-700", "bg-emerald-100 text-emerald-700", "bg-amber-100 text-amber-700",
  "bg-violet-100 text-violet-700", "bg-rose-100 text-rose-700", "bg-sky-100 text-sky-700",
]

export function InterleaveCard({ studentId }: { studentId: string }) {
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getReviewQueue(studentId).then(setItems).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [studentId])

  // 给每个不同 KC 分配一个颜色
  const colorOf = useMemo(() => {
    const map = new Map<string, string>()
    let i = 0
    for (const it of items) if (!map.has(it.kc_id)) map.set(it.kc_id, PALETTE[i++ % PALETTE.length])
    return map
  }, [items])

  const adjacentDifferent = useMemo(
    () => items.every((it, i) => i === 0 || it.kc_id !== items[i - 1].kc_id),
    [items],
  )

  if (loading) return <div className="text-xs text-slate-400 py-6 text-center animate-pulse">加载交错复习池…</div>
  if (err) return <div className="text-xs text-red-500 py-2">{err}</div>
  if (items.length === 0)
    return <div className="text-sm text-slate-400 py-6 text-center">今日复习池为空——没有到期需要交错巩固的知识点。</div>

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-semibold text-slate-800">今日交错复习池</span>
        <span className="text-xs text-slate-400">{items.length} 题</span>
      </div>
      <p className="text-xs text-slate-500 mb-3">刻意把不同知识点穿插排列——不让你连着刷同一类，训练"认出该用哪招"（对抗惰性知识）。</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((it, i) => (
          <span key={i} className={`px-2 py-1 rounded-md text-xs font-medium ${colorOf.get(it.kc_id)}`} title={it.kc_id}>
            {i + 1}. {it.kc_id.length > 12 ? it.kc_id.slice(0, 12) + "…" : it.kc_id}
          </span>
        ))}
      </div>
      <div className={`text-xs mt-2 ${adjacentDifferent ? "text-emerald-600" : "text-amber-600"}`}>
        {adjacentDifferent ? "✓ 相邻题知识点都不同（已交错）" : "部分相邻题相同（可用知识点不足以完全交错）"}
      </div>
    </div>
  )
}
