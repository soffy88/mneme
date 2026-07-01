import { useEffect, useMemo, useState } from "react"
import type { KU } from "../../api"
import { listKUs } from "../../api"
import { parseChinese002Desc } from "../../types"

function MingpianCard({ ku }: { ku: KU }) {
  const [show, setShow] = useState(false)
  const d = parseChinese002Desc(ku.description)
  const fullText = d.know_what || ku.name

  return (
    <div className="border border-lime-100 rounded-lg bg-white overflow-hidden">
      <div className="px-4 py-3 flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="text-sm font-medium text-slate-800 leading-relaxed">{ku.name}</div>
          {d.source && <div className="text-xs text-slate-400 mt-0.5">{d.source}</div>}
        </div>
        <button
          onClick={() => setShow(s => !s)}
          className="text-xs px-2 py-1 rounded border border-lime-300 text-lime-700 hover:bg-lime-50 shrink-0"
        >
          {show ? "收起" : "释义"}
        </button>
      </div>
      {show && fullText && fullText !== ku.name && (
        <div className="px-4 pb-3 border-t border-lime-50 bg-lime-50/40 pt-2 text-sm text-slate-700 leading-relaxed">
          {fullText}
        </div>
      )}
    </div>
  )
}

export function MingpianRecitation() {
  const [kus, setKus] = useState<KU[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")
  const [filterBook, setFilterBook] = useState("all")

  useEffect(() => {
    listKUs("chinese")
      .then(all => setKus(all.filter(k => k.ku_type === "mingpian")))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [])

  const books = useMemo(() => [...new Set(kus.map(k => k.book_name))].sort(), [kus])

  const filtered = useMemo(
    () => filterBook === "all" ? kus : kus.filter(k => k.book_name === filterBook),
    [kus, filterBook]
  )

  // 按 cluster（篇名）分组
  const grouped = useMemo(() => {
    const map = new Map<string, { name: string; order: number; kus: KU[] }>()
    for (const ku of filtered) {
      if (!map.has(ku.cluster_id))
        map.set(ku.cluster_id, { name: ku.cluster_name, order: ku.cluster_order, kus: [] })
      map.get(ku.cluster_id)!.kus.push(ku)
    }
    return [...map.values()].sort((a, b) => a.order - b.order)
  }, [filtered])

  if (loading) return (
    <div className="flex items-center justify-center min-h-64">
      <div className="text-lime-700 text-sm animate-pulse">加载名篇名句中…</div>
    </div>
  )
  if (err) return <div className="p-6 text-red-500 text-sm">{err}</div>

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="mb-5 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-lime-900">古诗文诵读</h1>
          <p className="text-sm text-slate-500 mt-1">共 {kus.length} 句名篇名句，64篇必背篇目</p>
        </div>
        <span className="text-xs px-2 py-1 rounded-full bg-lime-100 text-lime-700 font-medium mt-1">建设中</span>
      </div>

      <div className="flex gap-2 mb-5">
        <select
          value={filterBook}
          onChange={e => setFilterBook(e.target.value)}
          className="text-xs border border-slate-300 rounded-lg px-2 py-1.5 text-slate-700 bg-white focus:outline-none"
        >
          <option value="all">全部教材</option>
          {books.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        <span className="text-xs text-slate-400 self-center">{filtered.length} 句 · {grouped.length} 篇</span>
      </div>

      <div className="space-y-5">
        {grouped.map(g => (
          <div key={g.name}>
            <div className="text-xs font-semibold text-lime-700 uppercase tracking-wide mb-2 px-1">
              {g.name}
            </div>
            <div className="space-y-1.5">
              {g.kus.map(ku => <MingpianCard key={ku.id} ku={ku} />)}
            </div>
          </div>
        ))}
        {grouped.length === 0 && (
          <div className="text-center text-slate-400 py-12 text-sm">没有匹配的内容</div>
        )}
      </div>

      <div className="mt-8 p-4 bg-lime-50 rounded-xl border border-lime-100 text-xs text-lime-700">
        <div className="font-medium mb-1">🚧 建设中的功能</div>
        <ul className="space-y-0.5 text-lime-600">
          <li>· 背诵模式（遮住下句，逐行揭示）</li>
          <li>· 填空练习（随机挖空，检验记忆）</li>
          <li>· 朗读打分（语音识别，检测背诵正确率）</li>
          <li>· FSRS 间隔重复复习提醒</li>
        </ul>
      </div>
    </div>
  )
}
