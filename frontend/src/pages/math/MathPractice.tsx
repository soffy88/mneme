import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { currentStudentId, getKU, type KU } from "../../api"
import { RemediationLadder } from "../../components/RemediationLadder"
import { MathText } from "../../components/MathText"

/**
 * 数学练习/补救页：按掌握度自适应的补救阶梯（样例→淡出→苏格拉底→独立）。
 * 入口：/subjects/math/practice?ku=<ku_id>&name=<显示名>
 */
export function MathPractice() {
  const [params] = useSearchParams()
  const kuId = params.get("ku") ?? ""
  const name = params.get("name") ?? "知识点"
  const studentId = currentStudentId()
  const missing = !kuId

  const [ku, setKu] = useState<KU | null>(null)
  const [loading, setLoading] = useState(!missing)
  const [err, setErr] = useState("")

  useEffect(() => {
    if (missing) return
    getKU(kuId, studentId)
      .then(setKu)
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [kuId, studentId, missing])

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <div className="mb-4">
        <h1 className="text-xl font-bold text-slate-900"><MathText>{ku?.name ?? name}</MathText></h1>
        <p className="text-xs text-slate-400 mt-0.5">补救阶梯 · 给到刚好够用的帮助，再一点点撤掉</p>
      </div>

      {missing ? (
        <div className="text-sm text-red-500 py-4">缺少知识点</div>
      ) : loading ? (
        <div className="text-sm text-slate-400 py-12 text-center animate-pulse">加载中…</div>
      ) : err ? (
        <div className="text-sm text-red-500 py-4">{err}</div>
      ) : ku ? (
        <div className="card p-4">
          {ku.rich_content ? (
            <RemediationLadder ku={ku} />
          ) : (
            <div className="text-sm text-slate-400 py-8 text-center">
              这个知识点还没有"讲透"内容——可直接进苏格拉底引导。
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
