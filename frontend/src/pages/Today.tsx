import { currentStudentId } from "../api"
import { WeeklyDigest } from "../components/WeeklyDigest"
import { DailyPlanCard } from "../components/DailyPlanCard"
import { PageHeader } from "../components/ui"

/**
 * 今日（底部 tab）：跨学科的"今天学什么"——连续天数 + 今日计划（不限学科）。
 */
export function Today() {
  const sid = currentStudentId()
  if (!sid) return <div className="p-6 text-sm text-slate-500">请先登录。</div>
  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <PageHeader title="今日" subtitle="今天学什么、连续多少天——一眼看清。" />
      <div className="space-y-4">
        <WeeklyDigest studentId={sid} />
        <div className="card p-4">
          <DailyPlanCard studentId={sid} />
        </div>
      </div>
    </div>
  )
}
