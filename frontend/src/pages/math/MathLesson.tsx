import { useEffect, useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import { currentStudentId, listKUs, type KU } from "../../api"
import { KCGroup } from "../../components/KCGroup"
import { PageHeader } from "../../components/ui"
import { MATH_KU_TYPE_META } from "../../types"

export function MathLesson() {
  const [kus, setKus] = useState<KU[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")
  const [filterType, setFilterType] = useState<string>("all")
  const [filterGrade, setFilterGrade] = useState<string>("all")
  const [filterBook, setFilterBook] = useState<string>("all")
  const navigate = useNavigate()

  const studentId = useMemo(() => currentStudentId(), [])

  useEffect(() => {
    listKUs("math", studentId)
      .then(setKus)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  const books = useMemo(() => [...new Set(kus.map(k => k.book_name))].sort(), [kus])
  const grades = useMemo(() => [...new Set(kus.map(k => k.grade))].sort(), [kus])

  const filtered = useMemo(() => {
    return kus.filter(k => {
      if (filterType !== "all" && k.ku_type !== filterType) return false
      if (filterGrade !== "all" && k.grade !== filterGrade) return false
      if (filterBook !== "all" && k.book_name !== filterBook) return false
      return true
    })
  }, [kus, filterType, filterGrade, filterBook])

  const grouped = useMemo(() => {
    const map = new Map<string, { name: string; order: number; kus: KU[] }>()
    for (const ku of filtered) {
      const key = ku.cluster_id
      if (!map.has(key)) map.set(key, { name: ku.cluster_name, order: ku.cluster_order, kus: [] })
      map.get(key)!.kus.push(ku)
    }
    return [...map.values()].sort((a, b) => a.order - b.order)
  }, [filtered])

  const typeCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const k of kus) c[k.ku_type] = (c[k.ku_type] ?? 0) + 1
    return c
  }, [kus])

  const handleSocratic = (ku: KU) => {
    navigate(`/subjects/math/socratic?ku=${encodeURIComponent(ku.id)}&name=${encodeURIComponent(ku.name)}`)
  }
  const handlePractice = (ku: KU) => {
    navigate(`/subjects/math/practice?ku=${encodeURIComponent(ku.id)}&name=${encodeURIComponent(ku.name)}`)
  }

  if (loading) return (
    <div className="flex items-center justify-center min-h-64">
      <div className="text-slate-500 text-sm animate-pulse">加载数学知识点中…</div>
    </div>
  )
  if (err) return <div className="p-6 text-red-500 text-sm">{err}</div>

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <PageHeader title="数学知识体系" subtitle={`共 ${kus.length} 个知识点，${grouped.length} 个知识簇`} />

      {/* 知识类型筛选（仅数学类型） */}
      <div className="flex flex-wrap gap-2 mb-4">
        {Object.entries(MATH_KU_TYPE_META)
          .filter(([t]) => (typeCounts[t] ?? 0) > 0)
          .map(([t, meta]) => (
            <button
              key={t}
              onClick={() => setFilterType(filterType === t ? "all" : t)}
              className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium transition-all border ${
                filterType === t
                  ? `${meta.bg} ${meta.color} border-current shadow-sm`
                  : "bg-white text-slate-500 border-slate-200 hover:border-slate-400"
              }`}
            >
              {meta.label}
              <span className={filterType === t ? "opacity-100" : "opacity-60"}>{typeCounts[t] ?? 0}</span>
            </button>
          ))}
        {filterType !== "all" && (
          <button onClick={() => setFilterType("all")} className="text-xs text-slate-400 hover:text-slate-600 px-2">
            清除筛选 ×
          </button>
        )}
      </div>

      {/* 教材/年级筛选 */}
      <div className="flex gap-3 mb-5">
        <select
          value={filterGrade}
          onChange={e => { setFilterGrade(e.target.value); setFilterBook("all") }}
          className="text-xs border border-slate-300 rounded-lg px-2 py-1.5 text-slate-700 bg-white focus:outline-none"
        >
          <option value="all">全部年级</option>
          {grades.map(g => <option key={g} value={g}>{g}</option>)}
        </select>
        <select
          value={filterBook}
          onChange={e => setFilterBook(e.target.value)}
          className="flex-1 text-xs border border-slate-300 rounded-lg px-2 py-1.5 text-slate-700 bg-white focus:outline-none"
        >
          <option value="all">全部教材</option>
          {books
            .filter(b => filterGrade === "all" || kus.find(k => k.book_name === b && k.grade === filterGrade))
            .map(b => <option key={b} value={b}>{b}</option>)}
        </select>
      </div>

      {(filterType !== "all" || filterBook !== "all" || filterGrade !== "all") && (
        <div className="text-xs text-slate-400 mb-3">筛选结果：{filtered.length} 个知识点</div>
      )}

      {grouped.length === 0 ? (
        <div className="text-center text-slate-400 py-16 text-sm">没有匹配的知识点</div>
      ) : (
        grouped.map(g => (
          <KCGroup
            key={g.name}
            clusterName={g.name}
            kus={g.kus}
            studentId={studentId}
            onSocratic={handleSocratic}
            onPractice={handlePractice}
          />
        ))
      )}
    </div>
  )
}
