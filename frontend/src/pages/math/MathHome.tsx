import { Link } from "react-router-dom"
import { currentStudentId } from "../../api"
import { DailyPlanCard } from "../../components/DailyPlanCard"
import { WeeklyDigest } from "../../components/WeeklyDigest"
import { PageHeader } from "../../components/ui"

const TOOLS = [
  { to: "/subjects/math/lesson", icon: "📚", title: "知识体系", badge: "知识点地图",
    desc: "高中数学知识点，按知识簇分组，按类型/教材筛选，点开可苏格拉底引导",
    chip: "bg-indigo-50 text-indigo-600" },
  { to: "/subjects/math/dashboard", icon: "🪞", title: "成长档案", badge: "镜子",
    desc: "薄弱点排序 + 掌握度成长曲线——看清你是怎么学的、在怎样变好",
    chip: "bg-emerald-50 text-emerald-600" },
  { to: "/subjects/math/upload", icon: "📷", title: "上传试卷", badge: "冷启动",
    desc: "拍一张卷 → OCR 批改 → 错题接入认知档案，按遗忘曲线复习",
    chip: "bg-amber-50 text-amber-600" },
  { to: "/subjects/math/errors", icon: "📒", title: "错题本", badge: "检索约束",
    desc: "错题主动入口——先自己想通再看思路，重练走苏格拉底引导",
    chip: "bg-rose-50 text-rose-600" },
]

const TYPE_INFO = [
  { label: "概念", color: "bg-indigo-100 text-indigo-700",  desc: "数学定义" },
  { label: "定理", color: "bg-violet-100 text-violet-700",  desc: "定理/结论" },
  { label: "公式", color: "bg-rose-100 text-rose-700",      desc: "公式/法则" },
  { label: "方法", color: "bg-teal-100 text-teal-700",      desc: "解题方法" },
  { label: "模型", color: "bg-emerald-100 text-emerald-700", desc: "题型模型" },
]

export function MathHome() {
  const studentId = currentStudentId()
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <PageHeader title="数学 Mathematics" subtitle="人教A版 · 新高考 · 必修 → 选择性必修" />

      {/* 连续天数 + 本周摘要（留存） */}
      {studentId && (
        <div className="mb-4">
          <WeeklyDigest studentId={studentId} />
        </div>
      )}

      {/* 今日计划（即时价值） */}
      {studentId && (
        <div className="mb-6 card p-4">
          <DailyPlanCard studentId={studentId} subject="math" />
        </div>
      )}

      {/* 快速入口 */}
      <div className="space-y-2.5 mb-8">
        {TOOLS.map(t => (
          <Link
            key={t.to}
            to={t.to}
            className="flex items-start gap-3.5 p-4 rounded-xl bg-white border border-slate-100 shadow-card hover:border-indigo-200 hover:shadow-soft transition-all"
          >
            <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg ${t.chip}`}>{t.icon}</span>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <span className="font-semibold text-slate-800">{t.title}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{t.badge}</span>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed">{t.desc}</p>
            </div>
            <span className="text-slate-300 self-center">›</span>
          </Link>
        ))}
      </div>

      {/* 知识类型说明 */}
      <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
          数学知识类型
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_INFO.map(t => (
            <div key={t.label} className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${t.color}`}>{t.label}</span>
              <span className="text-xs text-slate-500">{t.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
