import { useEffect, useState } from "react"
import { getWeakRoots, type WeakRoot } from "../api"

/**
 * 前置图谱归因看板：对薄弱知识点上溯前置，提示"先补根、再补叶"。
 * 数据来自 GET /v1/weak-roots/{student_id}。
 */
export function WeakRoots({ studentId, onPractice }: { studentId: string; onPractice?: (kuId: string, name: string) => void }) {
  const [roots, setRoots] = useState<WeakRoot[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")

  useEffect(() => {
    getWeakRoots(studentId)
      .then(setRoots)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  if (loading) return <div className="text-xs text-slate-400 py-8 text-center animate-pulse">分析前置链…</div>
  if (err) return <div className="text-xs text-red-500 py-4">{err}</div>
  if (roots.length === 0)
    return (
      <div className="text-sm text-slate-400 py-8 text-center">
        暂未发现"前置断点"——薄弱点的前置都还稳，可以直接练薄弱点本身。
      </div>
    )

  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-semibold text-slate-800">前置断点（先补根）</span>
        <span className="text-xs text-slate-400">薄弱往往不在叶、在根</span>
      </div>
      <p className="text-xs text-slate-500 mb-3">这些薄弱知识点，根源可能在更底层的前置没掌握——先补前置，叶子会顺带松动。</p>
      <div className="space-y-2.5">
        {roots.map(r => (
          <div key={r.ku_id} className="p-3 rounded-lg border border-slate-100 bg-white">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm text-slate-800 truncate">{r.name}</span>
              <span className="text-xs text-slate-400">{Math.round(r.p_mastery * 100)}%</span>
            </div>
            <div className="pl-3 border-l-2 border-amber-200 space-y-1">
              {r.weak_prerequisites.map(p => (
                <button
                  key={p.ku_id}
                  onClick={() => onPractice?.(p.ku_id, p.name)}
                  className="w-full flex items-center gap-2 text-left text-xs text-slate-600 hover:text-indigo-700"
                >
                  <span className="text-amber-500">↳ 先补</span>
                  <span className="flex-1 truncate">{p.name}</span>
                  <span className="text-[10px] text-slate-400">
                    {p.status === "unpracticed" ? "未练" : `${Math.round((p.p_mastery ?? 0) * 100)}%`}
                  </span>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
