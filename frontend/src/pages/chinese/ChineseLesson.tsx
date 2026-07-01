import { useEffect, useMemo, useState } from "react"
import type { KU } from "../../api"
import { listKUs } from "../../api"
import { KCGroup } from "../../components/KCGroup"
import { PageHeader } from "../../components/ui"
import { CHINESE_KU_TYPE_META, CHINESE_TRACKS, TRACK_STYLE } from "../../types"
import type { ChineseTrack } from "../../types"

export function ChineseLesson() {
  const [kus, setKus] = useState<KU[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")
  const [track, setTrack] = useState<ChineseTrack | "all">("all")
  const [filterType, setFilterType] = useState<string>("all")
  const [filterBook, setFilterBook] = useState<string>("all")

  const studentId = useMemo(() => {
    try {
      const tok = localStorage.getItem("mneme_token")
      if (!tok) return undefined
      const payload = JSON.parse(atob(tok.split(".")[1]))
      return payload.sub as string
    } catch { return undefined }
  }, [])

  useEffect(() => {
    listKUs("chinese", studentId)
      .then(setKus)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  const books = useMemo(() => [...new Set(kus.map(k => k.book_name))].sort(), [kus])

  // 当前轨道下的类型列表
  const typesInTrack = useMemo(() => {
    return Object.entries(CHINESE_KU_TYPE_META)
      .filter(([, m]) => track === "all" || m.track === track)
      .map(([t]) => t)
  }, [track])

  const trackCount = useMemo(() => {
    const c: Record<string, number> = { all: kus.length }
    for (const ku of kus) {
      const meta = CHINESE_KU_TYPE_META[ku.ku_type]
      if (meta) c[meta.track] = (c[meta.track] ?? 0) + 1
    }
    return c
  }, [kus])

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const ku of kus) c[ku.ku_type] = (c[ku.ku_type] ?? 0) + 1
    return c
  }, [kus])

  const filtered = useMemo(() => {
    return kus.filter(k => {
      const meta = CHINESE_KU_TYPE_META[k.ku_type]
      if (track !== "all" && meta?.track !== track) return false
      if (filterType !== "all" && k.ku_type !== filterType) return false
      if (filterBook !== "all" && k.book_name !== filterBook) return false
      return true
    })
  }, [kus, track, filterType, filterBook])

  const grouped = useMemo(() => {
    const map = new Map<string, { name: string; order: number; kus: KU[] }>()
    for (const ku of filtered) {
      if (!map.has(ku.cluster_id))
        map.set(ku.cluster_id, { name: ku.cluster_name, order: ku.cluster_order, kus: [] })
      map.get(ku.cluster_id)!.kus.push(ku)
    }
    return [...map.values()].sort((a, b) => a.order - b.order)
  }, [filtered])

  const handleTrack = (t: ChineseTrack | "all") => {
    setTrack(t)
    setFilterType("all")
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-64">
      <div className="text-slate-500 text-sm animate-pulse">加载语文知识点中…</div>
    </div>
  )
  if (err) return <div className="p-6 text-red-500 text-sm">{err}</div>

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <PageHeader title="语文知识体系" subtitle={`共 ${kus.length} 个知识点 · ${grouped.length} 个知识簇`} />

      {/* 三轨 Tab */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => handleTrack("all")}
          className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
            track === "all" ? "bg-slate-800 text-white border-slate-800" : "bg-white text-slate-600 border-slate-200 hover:border-slate-400"
          }`}
        >
          全部 {trackCount.all}
        </button>
        {CHINESE_TRACKS.map(tr => {
          const s = TRACK_STYLE[tr]
          const active = track === tr
          return (
            <button
              key={tr}
              onClick={() => handleTrack(tr)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition-all ${
                active ? `${s.activeBg} ${s.color}` : `bg-white ${s.color} border-slate-200 hover:border-current`
              }`}
            >
              {tr}轨 {trackCount[tr] ?? 0}
            </button>
          )
        })}
      </div>

      {/* 知识类型 Pills */}
      <div className="flex flex-wrap gap-1.5 mb-4">
        {typesInTrack.map(t => {
          const meta = CHINESE_KU_TYPE_META[t]
          const active = filterType === t
          return (
            <button
              key={t}
              onClick={() => setFilterType(active ? "all" : t)}
              className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium border transition-all ${
                active ? `${meta.bg} ${meta.color} border-current shadow-sm` : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
              }`}
            >
              {meta.label}
              <span className={active ? "opacity-100" : "opacity-60"}>{typeCounts[t] ?? 0}</span>
            </button>
          )
        })}
        {filterType !== "all" && (
          <button onClick={() => setFilterType("all")} className="text-xs text-slate-400 hover:text-slate-600 px-2">
            清除 ×
          </button>
        )}
      </div>

      {/* 教材筛选 */}
      <div className="flex gap-3 mb-5">
        <select
          value={filterBook}
          onChange={e => setFilterBook(e.target.value)}
          className="flex-1 text-xs border border-slate-300 rounded-lg px-2 py-1.5 text-slate-700 bg-white focus:outline-none"
        >
          <option value="all">全部教材</option>
          {books.map(b => <option key={b} value={b}>{b}</option>)}
        </select>
        {(track !== "all" || filterType !== "all" || filterBook !== "all") && (
          <button
            onClick={() => { setTrack("all"); setFilterType("all"); setFilterBook("all") }}
            className="text-xs text-slate-400 hover:text-slate-600 px-2 border border-slate-200 rounded-lg"
          >
            重置
          </button>
        )}
      </div>

      {(track !== "all" || filterType !== "all" || filterBook !== "all") && (
        <div className="text-xs text-slate-400 mb-3">筛选结果：{filtered.length} 个知识点</div>
      )}

      {grouped.length === 0 ? (
        <div className="text-center text-slate-400 py-16 text-sm">没有匹配的知识点</div>
      ) : (
        grouped.map(g => (
          <KCGroup key={g.name} clusterName={g.name} kus={g.kus} studentId={studentId} />
        ))
      )}
    </div>
  )
}
