import { Link } from "react-router-dom"

const TOOLS = [
  {
    to: "/subjects/physics/lesson",
    icon: "📚",
    title: "知识体系",
    desc: "1551 个知识点，按知识簇分组，支持按类型/教材筛选",
    badge: "1551 KU",
    color: "bg-blue-50 border-blue-200 hover:bg-blue-100",
    titleColor: "text-blue-800",
  },
  {
    to: "/subjects/physics/practice",
    icon: "✏️",
    title: "专题练习",
    desc: "按知识点针对性练习（题库建设中，受力分析引导已可用）",
    badge: "即将上线",
    color: "bg-green-50 border-green-200 hover:bg-green-100",
    titleColor: "text-green-800",
  },
  {
    to: "/subjects/physics/force-analysis",
    icon: "⚡",
    title: "受力分析引导",
    desc: "AI 苏格拉底式引导，逐步分析力学情景，不直接给答案",
    badge: "已上线",
    color: "bg-purple-50 border-purple-200 hover:bg-purple-100",
    titleColor: "text-purple-800",
  },
]

const TYPE_INFO = [
  { label: "概念", color: "bg-blue-100 text-blue-700",    desc: "物理量定义" },
  { label: "规律", color: "bg-purple-100 text-purple-700", desc: "物理规律/定律" },
  { label: "模型", color: "bg-emerald-100 text-emerald-700",desc: "理想化模型" },
  { label: "实验", color: "bg-amber-100 text-amber-700",   desc: "实验探究设计" },
  { label: "方法", color: "bg-teal-100 text-teal-700",     desc: "科学思维方法" },
  { label: "公式", color: "bg-rose-100 text-rose-700",     desc: "计算公式" },
]

export function PhysicsHome() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">物理 Physics</h1>
        <p className="text-sm text-gray-500 mt-1">人教版 · 八年级 → 高中选必三 · 全 9 册</p>
      </div>

      {/* 快速入口 */}
      <div className="space-y-3 mb-8">
        {TOOLS.map(t => (
          <Link
            key={t.to}
            to={t.to}
            className={`flex items-start gap-4 p-4 rounded-xl border transition-all ${t.color}`}
          >
            <span className="text-2xl">{t.icon}</span>
            <div className="flex-1">
              <div className="flex items-center gap-2 mb-0.5">
                <span className={`font-semibold ${t.titleColor}`}>{t.title}</span>
                <span className="text-xs px-1.5 py-0.5 rounded bg-white/60 text-gray-600">{t.badge}</span>
              </div>
              <p className="text-xs text-gray-600">{t.desc}</p>
            </div>
            <span className="text-gray-400 text-sm self-center">›</span>
          </Link>
        ))}
      </div>

      {/* 知识类型说明 */}
      <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">
          物理知识类型（6 种）
        </h3>
        <div className="grid grid-cols-2 gap-2">
          {TYPE_INFO.map(t => (
            <div key={t.label} className="flex items-center gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${t.color}`}>{t.label}</span>
              <span className="text-xs text-gray-500">{t.desc}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 教材覆盖 */}
      <div className="mt-5 text-xs text-gray-400 leading-relaxed">
        <span className="font-medium text-gray-500">覆盖教材：</span>
        八上 · 八下 · 九全 · 高中必修一~三 · 选必一~三（共 1551 KU）
      </div>
    </div>
  )
}
