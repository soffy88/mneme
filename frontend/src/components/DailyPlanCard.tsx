import { useEffect, useState } from "react"
import { getDailyPlan, type DailyPlan } from "../api"

/**
 * 今日计划卡片。数据来自 GET /v1/daily-plan/{student_id}?subject=xxx。
 * 四优先级：P1 到期复习 > P2 错题 > P3 薄弱 > P4 新知。
 */
const PRIORITY_STYLE: Record<number, { dot: string; tag: string }> = {
  1: { dot: "bg-red-500",    tag: "到期复习" },
  2: { dot: "bg-amber-500", tag: "错题巩固" },
  3: { dot: "bg-yellow-500", tag: "薄弱突破" },
  4: { dot: "bg-indigo-500",   tag: "新知学习" },
}

export function DailyPlanCard({ studentId, subject }: { studentId: string; subject?: string }) {
  const [plan, setPlan] = useState<DailyPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getDailyPlan(studentId, subject)
      .then(setPlan)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId, subject])

  if (loading) return <div className="text-xs text-slate-400 py-8 text-center animate-pulse">加载今日计划…</div>
  if (err) return <div className="text-xs text-red-500 py-4">{err}</div>

  const tasks = plan?.tasks ?? []
  const totalMin = tasks.reduce((s, t) => s + t.estimated_minutes, 0)

  if (tasks.length === 0)
    return (
      <div className="text-sm text-slate-400 py-8 text-center">
        今天没有待办——上传试卷或开始一个新知识点来生成计划。
      </div>
    )

  return (
    <div>
      <div className="flex items-baseline justify-between mb-3">
        <span className="text-sm font-semibold text-slate-800">今日计划</span>
        <span className="text-xs text-slate-500">{tasks.length} 项 · 约 {totalMin} 分钟</span>
      </div>
      <div className="space-y-2">
        {tasks.map((t, i) => {
          const ps = PRIORITY_STYLE[t.priority] ?? PRIORITY_STYLE[4]
          return (
            <div key={i} className="flex items-start gap-3 p-3 rounded-lg border border-slate-100 bg-white">
              <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${ps.dot}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-800">{t.title}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{ps.tag}</span>
                </div>
                <p className="text-xs text-slate-500 mt-0.5">{t.reason} · 约 {t.estimated_minutes} 分钟</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
