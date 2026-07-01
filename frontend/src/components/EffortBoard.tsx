import { useEffect, useState } from "react"
import { getEffortfulGains, type EffortGain } from "../api"

/**
 * 努力收益看板（M-F · 对抗"努力错觉"）。
 * 展示"做得吃力、但记忆稳定性提升最多"的题——把费劲翻译成"学得最牢"的正反馈。
 * 数据来自 GET /v1/effortful-gains/{student_id}。
 */
export function EffortBoard({ studentId }: { studentId: string }) {
  const [gains, setGains] = useState<EffortGain[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getEffortfulGains(studentId)
      .then(setGains)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  if (loading) return <div className="text-xs text-slate-400 py-8 text-center animate-pulse">加载努力收益…</div>
  if (err) return <div className="text-xs text-red-500 py-4">{err}</div>
  if (gains.length === 0)
    return (
      <div className="text-sm text-slate-400 py-8 text-center">
        还没有努力收益记录——做几道有点难的题，"费劲但学得牢"的证据会出现在这里。
      </div>
    )

  const max = Math.max(...gains.map(g => g.effortful_gain), 1e-6)

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-semibold text-slate-800">努力收益</span>
        <span className="text-xs text-slate-400">越吃力、记忆越牢</span>
      </div>
      <p className="text-xs text-slate-500 mb-3">这些题你做得吃力，但正因为难，记忆稳定性提升得最多——这种费劲，恰是学得最牢的信号。</p>
      <div className="space-y-2">
        {gains.map((g, i) => (
          <div key={i} className="p-3 rounded-lg border border-amber-100 bg-amber-50">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm text-slate-800 truncate">{g.kc ?? "练习题"}</span>
              <span className="text-xs font-medium text-amber-700">+{(g.retention_delta).toFixed(1)} 天记忆</span>
            </div>
            <div className="h-1.5 bg-amber-100 rounded-full overflow-hidden">
              <div className="h-full bg-amber-500 rounded-full" style={{ width: `${Math.round((g.effortful_gain / max) * 100)}%` }} />
            </div>
            <div className="flex gap-3 text-[10px] text-slate-400 mt-1">
              <span>吃力度 {Math.round(g.struggle_score * 100)}%</span>
              <span>收益 {g.effortful_gain.toFixed(3)}</span>
              {g.occurred_at && <span>{g.occurred_at.slice(0, 10)}</span>}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
