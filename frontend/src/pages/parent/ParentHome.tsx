import { useEffect, useState } from "react"
import { currentStudentId, getParentChildren, getParentOverview, type Child, type ParentOverview } from "../../api"
import { WeeklyDigest } from "../../components/WeeklyDigest"
import { ParentAlerts } from "../../components/ParentAlerts"
import { DailyReportCard } from "../../components/DailyReportCard"

/**
 * 家长端首页：看孩子的"成长"而非分数。
 * 数据：GET /v1/parent/children + GET /v1/parent/overview/{student_id}。
 */
function ChildCard({ child, parentId }: { child: Child; parentId: string }) {
  const [ov, setOv] = useState<ParentOverview | null>(null)
  const [err, setErr] = useState("")

  useEffect(() => {
    getParentOverview(child.student_id).then(setOv).catch(e => setErr(e.message))
  }, [child.student_id])

  return (
    <div className="card p-4">
      <div className="flex items-baseline justify-between mb-3">
        <span className="font-semibold text-slate-800">{child.name ?? "孩子"}</span>
        <span className="text-xs text-slate-400">{child.grade ?? ""}</span>
      </div>
      {err ? (
        <div className="text-xs text-red-500">{err}</div>
      ) : !ov ? (
        <div className="text-xs text-slate-400 animate-pulse">加载成长摘要…</div>
      ) : (
        <div className="grid grid-cols-2 gap-3">
          <Stat label="连续学习" value={`${ov.streak.current_streak} 天`} hint={`最长 ${ov.streak.longest_streak} 天`} />
          <Stat label="练过的知识点" value={`${ov.total_kc_practiced}`} hint="覆盖广度" />
          <Stat label="当前薄弱点" value={`${ov.weak_kc_count}`} hint="越少越好" warn={ov.weak_kc_count > 0} />
          <Stat label="近期自主攻克" value={`${ov.recent_sessions}`} hint="苏格拉底会话" />
        </div>
      )}

      {/* 今日日报（可转发微信） */}
      <div className="mt-3">
        <DailyReportCard studentId={child.student_id} childName={child.name ?? undefined} />
      </div>

      {/* 每周成长摘要（复用 weekly_digest，家长视角） */}
      <div className="mt-3">
        <WeeklyDigest studentId={child.student_id} forParent />
      </div>

      {/* 5 类预警 */}
      <div className="mt-3 pt-3 border-t border-slate-100">
        <ParentAlerts studentId={child.student_id} parentId={parentId} />
      </div>
    </div>
  )
}

function Stat({ label, value, hint, warn }: { label: string; value: string; hint: string; warn?: boolean }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <div className={`text-lg font-bold ${warn ? "text-amber-600" : "text-slate-800"}`}>{value}</div>
      <div className="text-xs text-slate-600">{label}</div>
      <div className="text-[10px] text-slate-400">{hint}</div>
    </div>
  )
}

export function ParentHome() {
  const parentId = currentStudentId()   // 家长 JWT 的 sub 即家长 id
  const [children, setChildren] = useState<Child[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getParentChildren().then(setChildren).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [])

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-slate-900">家长端</h1>
        <p className="text-sm text-slate-500 mt-1">看孩子是怎么变好的——成长，而非一个分数。</p>
      </div>
      {loading ? (
        <div className="text-sm text-slate-400 py-12 text-center animate-pulse">加载…</div>
      ) : err ? (
        <div className="text-sm text-red-500 py-4">{err}</div>
      ) : children.length === 0 ? (
        <div className="text-sm text-slate-400 py-12 text-center">
          还没有绑定孩子——注册时用孩子的邀请码绑定即可。
        </div>
      ) : (
        <div className="space-y-4">
          {children.map(c => <ChildCard key={c.student_id} child={c} parentId={parentId ?? ""} />)}
        </div>
      )}
    </div>
  )
}
