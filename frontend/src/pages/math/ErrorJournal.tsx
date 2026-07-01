import { useEffect, useState } from "react"
import { useNavigate } from "react-router-dom"
import { currentStudentId, getErrorJournal, type ErrorJournalItem } from "../../api"
import { PageHeader, EmptyState, Loading } from "../../components/ui"

const ERROR_LABEL: Record<string, string> = {
  conceptual: "概念不清",
  transfer: "迁移弱",
  careless: "粗心",
  logic_break: "逻辑断裂",
  dontknow: "不会",
  unknown: "未分类",
}

/**
 * 错题本（主动入口）。检索约束：列表只显示知识点与错因，不直接展示答案；
 * 重练走苏格拉底引导（先自己想，再揭示思路）。
 */
export function ErrorJournal() {
  const studentId = currentStudentId()
  const [items, setItems] = useState<ErrorJournalItem[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState("")
  const navigate = useNavigate()

  useEffect(() => {
    if (!studentId) return
    getErrorJournal(studentId)
      .then(r => setItems(r.items))
      .catch(e => setErr(e.message))
      .finally(() => setLoading(false))
  }, [studentId])

  if (!studentId) return <div className="p-6 text-sm text-slate-500">请先登录后查看错题本。</div>

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <PageHeader
        title="错题本"
        subtitle="先自己想通，再看思路——重练用苏格拉底引导，不直接给答案。"
        action={
          <button
            onClick={() => navigate("/subjects/math/review")}
            className="px-3.5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium hover:bg-indigo-700 transition-colors"
          >
            🔁 检索复习
          </button>
        }
      />

      {loading ? (
        <Loading label="加载错题中…" />
      ) : err ? (
        <div className="text-sm text-red-500 py-4">{err}</div>
      ) : items.length === 0 ? (
        <EmptyState icon="📒">还没有错题——上传一张试卷开始积累。</EmptyState>
      ) : (
        <div className="space-y-2">
          {items.map(it => (
            <div key={it.question_id} className="flex items-center gap-3 p-3 rounded-xl border border-slate-100 bg-white hover:border-slate-200 hover:shadow-card transition-all">
              <div className="flex-1 min-w-0">
                <div className="text-sm text-slate-800 truncate">{it.kc_id}</div>
                <div className="text-xs text-slate-400 mt-0.5">
                  {ERROR_LABEL[it.error_tag] ?? it.error_tag} · {it.wrong_at.slice(0, 10)}
                </div>
              </div>
              {it.can_practice_variant && (
                <button
                  onClick={() => navigate(`/subjects/math/socratic?ku=${encodeURIComponent(it.kc_id)}&name=${encodeURIComponent(it.kc_id)}`)}
                  className="text-xs px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 hover:bg-indigo-100 shrink-0"
                >
                  苏格拉底重练
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
