import { Link } from "react-router-dom"
import { PageHeader } from "../../components/ui"

/**
 * 英语学科首页。英语暂无 KU 知识体系数据，先接已就绪的 AI 工具：
 * 作文引导（已上线）/ 阅读理解引导 / 口语陪练（建设中）。
 */
const TOOLS = [
  { to: "/subjects/english/essay", icon: "✍️", title: "作文引导", badge: "已上线",
    desc: "贴上你的英语作文 → 按评分维度给引导问题（不替你改写，引导你自己改）",
    chip: "bg-emerald-50 text-emerald-600", available: true },
  { to: "#", icon: "📖", title: "阅读理解引导", badge: "建设中",
    desc: "苏格拉底式带你读懂长难句与篇章（数据接入中）",
    chip: "bg-indigo-50 text-indigo-600", available: false },
  { to: "#", icon: "🎙️", title: "口语陪练", badge: "建设中",
    desc: "按话题陪你练口语，逐句反馈发音（接入中）",
    chip: "bg-amber-50 text-amber-600", available: false },
]

export function EnglishHome() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <PageHeader title="英语 English" subtitle="人教/外研 · AI 引导式练习（知识体系建设中）" />
      <div className="space-y-2.5">
        {TOOLS.map(t => {
          const inner = (
            <>
              <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg ${t.chip}`}>{t.icon}</span>
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-0.5">
                  <span className={`font-semibold ${t.available ? "text-slate-800" : "text-slate-400"}`}>{t.title}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">{t.badge}</span>
                </div>
                <p className={`text-xs leading-relaxed ${t.available ? "text-slate-500" : "text-slate-400"}`}>{t.desc}</p>
              </div>
            </>
          )
          return t.available ? (
            <Link key={t.title} to={t.to}
              className="flex items-start gap-3.5 p-4 rounded-xl bg-white border border-slate-100 shadow-card hover:border-indigo-200 hover:shadow-soft transition-all">
              {inner}
              <span className="text-slate-300 self-center">›</span>
            </Link>
          ) : (
            <div key={t.title} className="flex items-start gap-3.5 p-4 rounded-xl bg-white border border-slate-100 opacity-70 cursor-not-allowed">
              {inner}
            </div>
          )
        })}
      </div>
    </div>
  )
}
