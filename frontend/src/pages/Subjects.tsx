import { Link } from "react-router-dom"
import { PageHeader } from "../components/ui"

/**
 * 学科（底部 tab）：四科入口 2×2 格。
 */
const SUBJECTS = [
  { to: "/subjects/math", icon: "🔢", name: "数学", desc: "确定性内核 + 成长档案", chip: "bg-indigo-50 text-indigo-600" },
  { to: "/subjects/physics", icon: "⚛️", name: "物理", desc: "1551 知识点 · 受力分析引导", chip: "bg-violet-50 text-violet-600" },
  { to: "/subjects/chinese", icon: "📖", name: "语文", desc: "三轨13类 · 文言/诗文/成语", chip: "bg-amber-50 text-amber-600" },
  { to: "/subjects/english", icon: "🔤", name: "英语", desc: "作文引导 · 阅读 · 口语陪练", chip: "bg-emerald-50 text-emerald-600" },
]

export function Subjects() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <PageHeader title="学科" subtitle="选一门，进入它的知识体系与练习。" />
      <div className="grid grid-cols-2 gap-3">
        {SUBJECTS.map(s => (
          <Link
            key={s.to}
            to={s.to}
            className="card p-4 flex flex-col gap-2 hover:border-indigo-200 hover:shadow-soft transition-all"
          >
            <span className={`grid h-11 w-11 place-items-center rounded-xl text-xl ${s.chip}`}>{s.icon}</span>
            <div>
              <div className="font-semibold text-slate-800">{s.name}</div>
              <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{s.desc}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
