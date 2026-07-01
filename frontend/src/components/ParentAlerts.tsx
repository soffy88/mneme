import { useEffect, useState } from "react"
import { getAlerts, runAlertChecks, type ParentAlert } from "../api"

/**
 * 家长端 5 类预警：emotion/task_missing/time_drop/late_night/score_drop。
 * 列表展示已有预警 + "立即检查"按钮触发 run_alert_checks。
 */
const TYPE_META: Record<string, { icon: string; label: string }> = {
  emotion: { icon: "😟", label: "情绪/遇困难" },
  task_missing: { icon: "📋", label: "任务未完成" },
  time_drop: { icon: "⏳", label: "学习时长下降" },
  late_night: { icon: "🌙", label: "深夜学习" },
  score_drop: { icon: "📉", label: "掌握度下滑" },
}

const LEVEL_STYLE: Record<string, string> = {
  important: "bg-red-50 border-red-200 text-red-800",
  attention: "bg-amber-50 border-amber-200 text-amber-800",
  notice: "bg-slate-50 border-slate-200 text-slate-700",
}

export function ParentAlerts({ studentId, parentId }: { studentId: string; parentId: string }) {
  const [alerts, setAlerts] = useState<ParentAlert[]>([])
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [err, setErr] = useState("")

  const load = () => {
    getAlerts(studentId, parentId)
      .then(setAlerts)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }

  useEffect(load, [studentId, parentId])

  const check = async () => {
    setChecking(true); setErr("")
    try {
      await runAlertChecks(studentId, parentId)
      load()
    } catch (e) {
      setErr(e instanceof Error ? e.message : "检查失败")
    } finally {
      setChecking(false)
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-slate-500">预警</span>
        <button
          onClick={check}
          disabled={checking}
          className="text-[11px] px-2 py-1 rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-50"
        >
          {checking ? "检查中…" : "立即检查"}
        </button>
      </div>
      {err && <div className="text-xs text-red-500 mb-1">{err}</div>}
      {loading ? (
        <div className="text-xs text-slate-400">加载预警…</div>
      ) : alerts.length === 0 ? (
        <div className="text-xs text-slate-400">暂无预警，一切正常 ✓</div>
      ) : (
        <div className="space-y-1.5">
          {alerts.map(a => {
            const meta = TYPE_META[a.type ?? ""] ?? { icon: "ℹ️", label: a.type ?? "提醒" }
            const style = LEVEL_STYLE[a.level ?? ""] ?? LEVEL_STYLE.notice
            return (
              <div key={a.id} className={`flex items-start gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${style}`}>
                <span>{meta.icon}</span>
                <div className="flex-1">
                  <div className="font-medium">{meta.label}</div>
                  <div className="opacity-90">{a.content}</div>
                </div>
                {a.created_at && <span className="opacity-60 shrink-0">{a.created_at.slice(5, 10)}</span>}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
