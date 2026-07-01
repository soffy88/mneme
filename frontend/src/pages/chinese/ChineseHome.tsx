import { Link } from "react-router-dom"
import { PageHeader } from "../../components/ui"

const TOOLS = [
  { to: "/subjects/chinese/lesson", icon: "📚", title: "知识体系", badge: "3287 KU",
    desc: "3287 个知识点，三轨13类，按教材/年级/类型筛选", chip: "bg-indigo-50 text-indigo-600", available: true },
  { to: "/subjects/chinese/wenyan-words", icon: "📖", title: "文言实词本", badge: "建设中",
    desc: "953 个文言词语，义项·例句·通假·活用，按册浏览", chip: "bg-amber-50 text-amber-600", available: true },
  { to: "/subjects/chinese/mingpian", icon: "🎋", title: "古诗文诵读", badge: "建设中",
    desc: "224 句名篇名句，64 篇必背篇目，按文本归组诵读", chip: "bg-emerald-50 text-emerald-600", available: true },
  { to: "/subjects/chinese/dict", icon: "🔍", title: "字词典", badge: "建设中",
    desc: "成语·文化常识检索（数据接入中）", chip: "bg-slate-100 text-slate-400", available: false },
]

const TRACK_INFO = [
  { label: "积累轨", color: "bg-amber-100 text-amber-700",  types: "文言词语 · 文言句式 · 名篇名句 · 成语 · 文化常识" },
  { label: "鉴赏轨", color: "bg-indigo-100 text-indigo-700", types: "信息阅读 · 小说 · 散文 · 文言 · 诗词鉴赏" },
  { label: "表达轨", color: "bg-red-100 text-red-700",    types: "写作方法 · 口语交际 · 沟通处世" },
]

export function ChineseHome() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <PageHeader title="语文 Chinese" subtitle="统编版 · 七年级 → 高中选必下 · 全 13 册" />

      <div className="space-y-2.5 mb-8">
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
            <Link key={t.to} to={t.to}
              className="flex items-start gap-3.5 p-4 rounded-xl bg-white border border-slate-100 shadow-card hover:border-indigo-200 hover:shadow-soft transition-all">
              {inner}
              <span className="text-slate-300 self-center">›</span>
            </Link>
          ) : (
            <div key={t.to} className="flex items-start gap-3.5 p-4 rounded-xl bg-white border border-slate-100 opacity-70 cursor-not-allowed">
              {inner}
            </div>
          )
        })}
      </div>

      <div className="bg-slate-50 rounded-2xl p-4 border border-slate-100">
        <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">三轨13类知识体系</h3>
        <div className="space-y-2">
          {TRACK_INFO.map(t => (
            <div key={t.label} className="flex items-start gap-2">
              <span className={`px-1.5 py-0.5 rounded text-xs font-medium shrink-0 ${t.color}`}>{t.label}</span>
              <span className="text-xs text-slate-500 leading-5">{t.types}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 text-xs text-slate-400 leading-relaxed">
        <span className="font-medium text-slate-500">覆盖教材：</span>
        初中语文七~九年级 · 高中必修上下 · 选必上中下（共 3287 KU）
      </div>
    </div>
  )
}
