import { useEffect, useState } from "react"
import { getWeeklyDigest, type WeeklyDigest as Digest } from "../api"

/**
 * 留存引擎：连续学习天数 + 本周成长摘要（社交货币 + 再触达）。
 * 未活跃时给"别断了连续"的轻提醒——对抗冷启动流失（产品头号风险）。
 */
export function WeeklyDigest({ studentId, forParent = false }: { studentId: string; forParent?: boolean }) {
  const [d, setD] = useState<Digest | null>(null)
  const [err, setErr] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getWeeklyDigest(studentId).then(setD).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [studentId])

  if (loading) return <div className="text-xs text-slate-400 py-4 text-center animate-pulse">加载本周摘要…</div>
  if (err) return <div className="text-xs text-red-500 py-2">{err}</div>
  if (!d) return null

  const nudge = !d.active_today && d.current_streak > 0

  return (
    <div className={`rounded-xl p-4 border ${nudge ? "bg-amber-50 border-amber-200" : "bg-gradient-to-br from-amber-50 to-red-50 border-amber-100"}`}>
      <div className="flex items-center gap-3">
        <div className="text-3xl">🔥</div>
        <div className="flex-1">
          <div className="text-2xl font-bold text-amber-700 leading-none">
            {d.current_streak} <span className="text-sm font-normal text-slate-500">天连续</span>
          </div>
          <div className="text-xs text-slate-500 mt-1">{d.headline}</div>
        </div>
      </div>

      {nudge && (
        <div className="mt-3 text-sm text-amber-800 bg-white/60 rounded-lg px-3 py-2">
          {forParent
            ? `孩子今天还没学习——连续 ${d.current_streak} 天的记录别断在今天，可以轻轻提醒一下。`
            : `今天还没练——做一道就能保住这 ${d.current_streak} 天的连续记录。别断在这。`}
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 mt-3 text-center">
        <Stat v={d.n_interactions_7d} label="本周练题" />
        <Stat v={d.distinct_kcs_7d} label="覆盖知识点" />
        <Stat v={d.accuracy_7d != null ? `${Math.round(d.accuracy_7d * 100)}%` : "—"} label="正确率" />
      </div>
    </div>
  )
}

function Stat({ v, label }: { v: number | string; label: string }) {
  return (
    <div className="rounded-lg bg-white/70 px-2 py-1.5">
      <div className="text-base font-bold text-slate-800">{v}</div>
      <div className="text-[10px] text-slate-500">{label}</div>
    </div>
  )
}
