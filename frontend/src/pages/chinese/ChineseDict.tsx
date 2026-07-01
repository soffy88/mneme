export function ChineseDict() {
  return (
    <div className="max-w-2xl mx-auto px-4 py-10">
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-800">字词典</h1>
          <p className="text-sm text-slate-500 mt-1">成语 · 文化常识 · 汉字检索</p>
        </div>
        <span className="text-xs px-2 py-1 rounded-full bg-slate-100 text-slate-500 font-medium mt-1">建设中</span>
      </div>

      {/* 搜索框占位 */}
      <div className="mb-8">
        <div className="relative">
          <input
            disabled
            placeholder="搜索汉字、成语、文化常识…"
            className="w-full text-sm border border-slate-300 rounded-xl px-4 py-3 pr-10 bg-slate-50 text-slate-400 cursor-not-allowed"
          />
          <span className="absolute right-3 top-3 text-slate-300">🔍</span>
        </div>
      </div>

      {/* 即将上线 */}
      <div className="grid grid-cols-1 gap-3">
        {[
          { icon: "📝", title: "成语词典", desc: "1500+ 常用成语，含出处·典故·近义辨析" },
          { icon: "🏛️", title: "文化常识库", desc: "古代官制·礼仪·天文·地理全覆盖" },
          { icon: "字", title: "汉字字源", desc: "字形演变、部首拆分、六书分析" },
          { icon: "📜", title: "文言虚词手册", desc: "18 个高考必考虚词，例句精讲" },
        ].map(item => (
          <div
            key={item.title}
            className="flex items-start gap-3 p-4 rounded-xl border border-dashed border-slate-200 bg-slate-50 opacity-60"
          >
            <span className="text-xl w-8 text-center">{item.icon}</span>
            <div>
              <div className="text-sm font-medium text-slate-500">{item.title}</div>
              <div className="text-xs text-slate-400 mt-0.5">{item.desc}</div>
            </div>
          </div>
        ))}
      </div>

      <div className="mt-10 p-4 bg-slate-50 rounded-xl border border-slate-100 text-xs text-slate-500 text-center leading-relaxed">
        字词典模块正在建设中，数据接入完成后上线。
        <br />
        现有 3287 个知识点可在 <a href="/subjects/chinese/lesson" className="text-amber-600 underline">知识体系</a> 中查阅。
      </div>
    </div>
  )
}
