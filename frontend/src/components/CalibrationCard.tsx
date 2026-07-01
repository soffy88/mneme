import { useEffect, useState } from "react"
import { getCalibration, type Calibration } from "../api"

/**
 * 判断准度（JOL 校准）：自测里"预测把握 vs 实际对错"的吻合度。
 * brier 越低越准；overconfidence>0=高估自己，<0=低估自己。
 */
export function CalibrationCard({ studentId }: { studentId: string }) {
  const [cal, setCal] = useState<Calibration | null>(null)
  const [err, setErr] = useState("")
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getCalibration(studentId).then(setCal).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [studentId])

  if (loading) return <div className="text-xs text-slate-400 py-6 text-center animate-pulse">加载判断准度…</div>
  if (err) return <div className="text-xs text-red-500 py-3">{err}</div>
  if (!cal || cal.n === 0)
    return (
      <div className="text-sm text-slate-400 py-6 text-center">
        还没有自测记录——去「自测」预测一下把握，练"知道自己会不会"的准度。
      </div>
    )

  const oc = cal.overconfidence ?? 0
  const tag = oc > 0.1 ? { t: "偏高估自己", c: "text-red-600" }
    : oc < -0.1 ? { t: "偏低估自己", c: "text-indigo-600" }
    : { t: "判断挺准", c: "text-emerald-600" }

  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-sm font-semibold text-slate-800">判断准度（JOL）</span>
        <span className="text-xs text-slate-400">{cal.n} 次自测</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center">
        <div className="rounded-lg bg-slate-50 px-2 py-2">
          <div className="text-lg font-bold text-slate-800">{cal.brier != null ? cal.brier.toFixed(2) : "—"}</div>
          <div className="text-[10px] text-slate-500">Brier（越低越准）</div>
        </div>
        <div className="rounded-lg bg-slate-50 px-2 py-2">
          <div className="text-lg font-bold text-slate-800">{cal.mean_predicted != null ? Math.round(cal.mean_predicted * 100) : "—"}%</div>
          <div className="text-[10px] text-slate-500">平均预测把握</div>
        </div>
        <div className="rounded-lg bg-slate-50 px-2 py-2">
          <div className="text-lg font-bold text-slate-800">{cal.accuracy != null ? Math.round(cal.accuracy * 100) : "—"}%</div>
          <div className="text-[10px] text-slate-500">实际正确率</div>
        </div>
      </div>
      <p className={`text-xs mt-2 ${tag.c}`}>
        {tag.t}（预测与实际差 {oc >= 0 ? "+" : ""}{Math.round(oc * 100)}%）
      </p>
    </div>
  )
}
