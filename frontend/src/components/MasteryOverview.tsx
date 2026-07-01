import { useEffect, useState } from "react"
import { getMasteryOverview, type MasteryItem } from "../api"

/**
 * 掌握度总览（薄弱在前）。点击某知识点回调 onSelect（用于联动成长曲线）。
 * 数据来自 GET /v1/mastery/{student_id}（已按 effective_mastery 升序）。
 */
function barColor(m: number): string {
  if (m < 0.4) return "bg-red-400"
  if (m < 0.6) return "bg-amber-400"
  if (m < 0.8) return "bg-yellow-400"
  return "bg-emerald-500"
}

export function MasteryOverview({ studentId, onSelect, selectedKc }: {
  studentId: string
  onSelect?: (kcId: string) => void
  selectedKc?: string
}) {
  const [items, setItems] = useState<MasteryItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getMasteryOverview(studentId)
      .then(setItems)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  if (loading) return <div className="text-xs text-slate-400 py-8 text-center animate-pulse">加载掌握度…</div>
  if (err) return <div className="text-xs text-red-500 py-4">{err}</div>
  if (items.length === 0)
    return (
      <div className="text-sm text-slate-400 py-8 text-center">
        还没有掌握度数据——上传一张卷或做几道题，薄弱点会在这里排序出现。
      </div>
    )

  return (
    <div className="space-y-1.5">
      {items.map(it => {
        const m = it.effective_mastery
        const active = selectedKc === it.kc_id
        return (
          <button
            key={it.kc_id}
            onClick={() => onSelect?.(it.kc_id)}
            className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-left transition-colors border ${
              active ? "bg-indigo-50 border-indigo-300" : "bg-white border-slate-100 hover:bg-slate-50"
            }`}
          >
            <span className="flex-1 text-sm text-slate-700 truncate">{it.kc_id}</span>
            <div className="w-24 h-1.5 bg-slate-200 rounded-full overflow-hidden">
              <div className={`h-full rounded-full ${barColor(m)}`} style={{ width: `${Math.round(m * 100)}%` }} />
            </div>
            <span className="text-xs text-slate-500 w-9 text-right">{Math.round(m * 100)}%</span>
          </button>
        )
      })}
    </div>
  )
}
