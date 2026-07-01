import { useEffect, useMemo, useState } from "react"
import { getMasteryCurve, type CurvePoint } from "../api"

/**
 * 成长曲线（掌握度月度时间序列）。纯手写 SVG，零图表依赖。
 * 数据来自 GET /v1/mastery/curve/{student_id}/{kc_id}（mastery_snapshots）。
 */
const ERROR_LABEL: Record<string, string> = {
  conceptual: "概念不清",
  transfer: "迁移弱",
  careless: "粗心",
  logic_break: "逻辑断裂",
  dontknow: "不会",
}

export function GrowthCurve({ studentId, kcId, kcName }: { studentId: string; kcId: string; kcName?: string }) {
  const [points, setPoints] = useState<CurvePoint[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getMasteryCurve(studentId, kcId)
      .then(setPoints)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId, kcId])

  const W = 520, H = 180, PAD = 28
  const path = useMemo(() => {
    const vals = points.map(p => p.long_term_mastery).filter((v): v is number => v != null)
    if (vals.length === 0) return { line: "", dots: [] as { x: number; y: number; p: CurvePoint }[] }
    const n = points.length
    const x = (i: number) => PAD + (n <= 1 ? 0 : (i / (n - 1)) * (W - 2 * PAD))
    const y = (v: number) => H - PAD - v * (H - 2 * PAD) // 0..1 → 底..顶
    const dots = points.map((p, i) => ({ x: x(i), y: y(p.long_term_mastery ?? 0), p }))
    const line = dots.map((d, i) => `${i === 0 ? "M" : "L"}${d.x.toFixed(1)},${d.y.toFixed(1)}`).join(" ")
    return { line, dots }
  }, [points])

  if (loading) return <div className="text-xs text-slate-400 py-8 text-center animate-pulse">加载成长曲线…</div>
  if (err) return <div className="text-xs text-red-500 py-4">{err}</div>
  if (points.length === 0)
    return (
      <div className="text-xs text-slate-400 py-8 text-center">
        {kcName ?? kcId} 暂无历史快照——多练几次，成长曲线会在这里生长。
      </div>
    )

  const last = points[points.length - 1]
  return (
    <div>
      <div className="flex items-baseline justify-between mb-2">
        <span className="text-sm font-semibold text-slate-800">{kcName ?? kcId} · 成长曲线</span>
        <span className="text-xs text-slate-500">
          当前 {last.long_term_mastery != null ? `${Math.round(last.long_term_mastery * 100)}%` : "—"}
          {last.dominant_error_type && ` · 主要错因：${ERROR_LABEL[last.dominant_error_type] ?? last.dominant_error_type}`}
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="掌握度成长曲线">
        {/* 参考线 0.6 掌握线 */}
        <line x1={PAD} x2={W - PAD} y1={H - PAD - 0.6 * (H - 2 * PAD)} y2={H - PAD - 0.6 * (H - 2 * PAD)}
          stroke="#e5e7eb" strokeWidth={1} strokeDasharray="4 4" />
        <text x={W - PAD} y={H - PAD - 0.6 * (H - 2 * PAD) - 4} textAnchor="end" className="fill-slate-400" fontSize={9}>掌握线 60%</text>
        <path d={path.line} fill="none" stroke="#10b981" strokeWidth={2} strokeLinejoin="round" />
        {path.dots.map((d, i) => (
          <g key={i}>
            <circle cx={d.x} cy={d.y} r={3.5} className="fill-emerald-500" />
            <text x={d.x} y={H - 8} textAnchor="middle" className="fill-slate-400" fontSize={8}>
              {d.p.month.slice(2, 7)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}
