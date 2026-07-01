import { Link } from "react-router-dom"
import { PageHeader } from "../../components/ui"

const TOOLS = [
  { to: "/subjects/physics/lesson", icon: "📚", title: "知识体系", badge: "1551 KU",
    desc: "1551 个知识点，按知识簇分组，支持按类型/教材筛选", chip: "bg-indigo-50 text-indigo-600" },
  { to: "/subjects/physics/practice", icon: "✏️", title: "专题练习", badge: "即将上线",
    desc: "按知识点针对性练习（题库建设中，受力分析引导已可用）", chip: "bg-emerald-50 text-emerald-600" },
  { to: "/subjects/physics/force-analysis", icon: "⚡", title: "受力分析引导", badge: "已上线",
    desc: "AI 苏格拉底式引导，逐步分析力学情景，不直接给答案", chip: "bg-amber-50 text-amber-600" },
]

const TYPE_INFO = [
  { label: "概念", color: "bg-indigo-100 text-indigo-700",  desc: "物理量定义" },
  { label: "规律", color: "bg-violet-100 text-violet-700",  desc: "物理规律/定律" },
  { label: "模型", color: "bg-emerald-100 text-emerald-700", desc: "理想化模型" },
  { label: "实验", color: "bg-amber-100 text-amber-700",    desc: "实验探究设计" },
  { label: "方法", color: "bg-teal-100 text-teal-700",      desc: "科学思维方法" },
  { label: "公式", color: "bg-rose-100 text-rose-700",      desc: "计算公式" },
]

export function PhysicsHome() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <PageHeader title="物理 Physics" subtitle="人教版 · 八年级 → 高中选必三 · 全 9 册" />

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
      <div className="bg-slate-50 rounded-2xl p-4 border border-slate-100">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">物理知识类型（6 种）</h3>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_INFO.map(t => (
            <div key={t.label} className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${t.color}`}>{t.label}</span>
              <span className="text-xs text-slate-500">{t.desc}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 text-xs text-slate-400 leading-relaxed">
        <span className="font-medium text-slate-500">覆盖教材：</span>
        八上 · 八下 · 九全 · 高中必修一~三 · 选必一~三（共 1551 KU）
      </div>
    </div>
  )
}
