import { useEffect, useMemo, useState } from "react"
import type { KU } from "../../api"
import { listKUs } from "../../api"
import { parseChinese002Desc } from "../../types"

function WenyanCard({ ku }: { ku: KU }) {
  const [open, setOpen] = useState(false)
  const d = parseChinese002Desc(ku.description)

  // 从 name 里提取 "词·义项（来源）" 格式
  const nameParts = ku.name.split("·")
  const word = nameParts[0]?.trim() ?? ku.name
  const sense = nameParts.slice(1).join("·").trim()

  return (
    <div
      className="border border-amber-100 rounded-lg bg-white overflow-hidden cursor-pointer hover:border-amber-300 transition-all"
      onClick={() => setOpen(o => !o)}
    >
      <div className="px-3 py-2.5 flex items-start gap-3">
        <span className="text-base font-bold text-amber-800 min-w-[2rem]">{word}</span>
        <div className="flex-1 min-w-0">
          {sense && <div className="text-xs text-slate-600 truncate">{sense}</div>}
          {d.know_what && <div className="text-xs text-slate-500 truncate mt-0.5">{d.know_what}</div>}
        </div>
        {d.wenyan && (
          <span className="text-xs text-amber-600 shrink-0">
            {d.wenyan.match(/词性:([^；]+)/)?.[1] ?? ""}
          </span>
        )}
      </div>
      {open && (
        <div className="px-3 pb-3 border-t border-amber-50 bg-amber-50/50 space-y-1.5 pt-2">
          {d.know_what && (
            <div className="text-sm text-slate-800">{d.know_what}</div>
          )}
          {d.wenyan && (
            <div className="text-xs text-slate-600 leading-relaxed">
              {d.wenyan.split("；").map((seg, i) => (
                <span key={i} className="mr-3">{seg}</span>
              ))}
            </div>
          )}
          {d.source && <div className="text-xs text-slate-400">出处：{d.source}</div>}
        </div>
      )}
    </div>
  )
}

export function WenyanWordBook() {
  const [kus, setKus] = useState<KU[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")
  const [filterBook, setFilterBook] = useState("all")
  const [search, setSearch] = useState("")

  useEffect(() => {
    listKUs("chinese")
      .then(all => setKus(all.filter(k => k.ku_type === "wenyan_word")))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  const books = useMemo(() => [...new Set(kus.map(k => k.book_name))].sort(), [kus])

  const filtered = useMemo(() => {
    let out = kus
    if (filterBook !== "all") out = out.filter(k => k.book_name === filterBook)
    if (search.trim()) {
      const q = search.trim()
      out = out.filter(k => k.name.includes(q) || (k.description ?? "").includes(q))
    }
    return out
  }, [kus, filterBook, search])

  if (loading) return (
    <div className="flex items-center justify-center min-h-64">
      <div className="text-amber-600 text-sm animate-pulse">加载文言实词中…</div>
    </div>
  )
  if (err) return <div className="p-6 text-red-500 text-sm">{err}</div>

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-amber-900">文言实词本</h1>
          <p className="text-sm text-slate-500 mt-1">共 {kus.length} 条实词，对照高考120实词+18虚词</p>
        </div>
        <span className="text-xs px-2 py-1 rounded-full bg-amber-100 text-amber-700 font-medium mt-1">建设中</span>
      </div>

      <div className="flex gap-2 mb-4">
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="搜索词语…"
          className="flex-1 text-sm border border-slate-300 rounded-lg px-3 py-1.5 focus:outline-none focus:border-amber-400"
        />
        <select
          value={filterBook}
          onChange={e => setFilterBook(e.target.value)}
          className="text-xs border border-slate-300 rounded-lg px-2 py-1.5 text-slate-700 bg-white focus:outline-none"
        >
          <option value="all">全部教材</option>
          {books.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>

      <div className="text-xs text-slate-400 mb-3">{filtered.length} 条</div>

      <div className="space-y-1.5">
        {filtered.map(ku => <WenyanCard key={ku.id} ku={ku} />)}
        {filtered.length === 0 && (
          <div className="text-center text-slate-400 py-12 text-sm">没有匹配的词语</div>
        )}
      </div>

      <div className="mt-8 p-4 bg-amber-50 rounded-xl border border-amber-100 text-xs text-amber-700">
        <div className="font-medium mb-1">🚧 建设中的功能</div>
        <ul className="space-y-0.5 text-amber-600">
          <li>· 高考120实词体系对照标注</li>
          <li>· 词语义项卡片（正面词语/反面释义）闪卡练习</li>
          <li>· 通假字 / 古今异义 / 词类活用 分类筛选</li>
          <li>· 生词本（标记未掌握词语）</li>
        </ul>
      </div>
    </div>
  )
}
