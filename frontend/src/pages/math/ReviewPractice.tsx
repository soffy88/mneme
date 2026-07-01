import { useEffect, useState } from "react"
import { currentStudentId, getDueReview, postInteraction, type DueReviewItem } from "../../api"
import { MathText } from "../../components/MathText"
import { PageHeader, EmptyState, Loading } from "../../components/ui"

/**
 * 错题/到期复习 · 检索练习流（M-C 红线）：
 *   未作答不可见答案；先主动回忆→自评→才揭示；看答案=Again（记忆重置）。
 * 自评映射 FSRS：秒杀→Easy / 正常→Good / 吃力→Hard / 没做出→Again。
 */
type Phase = "recall" | "rate" | "revealed"

export function ReviewPractice() {
  const studentId = currentStudentId()
  const [items, setItems] = useState<DueReviewItem[]>([])
  const [loading, setLoading] = useState(!!studentId)
  const [err, setErr] = useState("")
  const [idx, setIdx] = useState(0)
  const [phase, setPhase] = useState<Phase>("recall")
  const [busy, setBusy] = useState(false)
  const [ratingLabel, setRatingLabel] = useState("")

  useEffect(() => {
    if (!studentId) return
    getDueReview(studentId).then(setItems).catch(e => setErr(e.message)).finally(() => setLoading(false))
  }, [studentId])

  const cur = items[idx]

  const record = async (
    flags: { is_correct: boolean; struggled?: boolean; effortless?: boolean; used_answer?: boolean },
    label: string,
  ) => {
    if (!studentId || !cur || busy) return
    setBusy(true)
    try {
      await postInteraction({ student_id: studentId, kc_id: cur.kc_id, source: "review", ...flags })
      setRatingLabel(label)
      setPhase("revealed")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提交失败")
    } finally {
      setBusy(false)
    }
  }

  const next = () => {
    setPhase("recall"); setRatingLabel(""); setErr("")
    setIdx(i => i + 1)
  }

  if (!studentId) return <div className="p-6 text-sm text-slate-500">请先登录。</div>

  return (
    <div className="max-w-xl mx-auto px-4 py-6">
      <PageHeader title="检索复习" subtitle="先自己回忆作答，再揭示——看答案=记忆重置(Again)，所以先认真想。" />
      {err && <div className="text-xs text-red-500 mb-3">{err}</div>}

      {loading ? (
        <Loading label="加载到期复习…" />
      ) : items.length === 0 ? (
        <EmptyState icon="🎉">暂无到期复习——没有需要现在巩固的错题。</EmptyState>
      ) : idx >= items.length ? (
        <EmptyState icon="✅">本轮检索复习完成（{items.length} 题）。</EmptyState>
      ) : cur ? (
        <div className="card p-5">
          <div className="flex items-center justify-between mb-3">
            <span className="text-xs text-slate-400">第 {idx + 1} / {items.length} 题 · {cur.kc_id}</span>
          </div>

          {/* 题面（始终可见） */}
          <MathText className="block text-sm text-slate-800 whitespace-pre-wrap leading-relaxed mb-4">{cur.variant_question}</MathText>

          {phase === "recall" && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">在纸上做一遍，做完点"我做完了"自评；想不起来再看答案（按 Again 计）。</p>
              <div className="flex gap-3">
                <button disabled={busy} onClick={() => setPhase("rate")}
                  className="flex-1 py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">
                  我做完了，自评
                </button>
                <button disabled={busy}
                  onClick={() => record({ is_correct: false, used_answer: true }, "看了答案 = Again（记忆重置）")}
                  className="px-4 py-2.5 bg-slate-100 text-slate-600 rounded-lg text-sm disabled:opacity-50">
                  看答案
                </button>
              </div>
            </div>
          )}

          {phase === "rate" && (
            <div className="space-y-2">
              <p className="text-xs text-slate-500">如实自评（决定下次复习间隔）：</p>
              <button disabled={busy} onClick={() => record({ is_correct: true, effortless: true }, "秒杀 → Easy（间隔拉长）")}
                className="w-full py-2 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-lg text-sm">秒杀（很轻松做对）</button>
              <button disabled={busy} onClick={() => record({ is_correct: true }, "正常 → Good")}
                className="w-full py-2 bg-emerald-50 text-emerald-700 border border-emerald-200 rounded-lg text-sm">做对了（正常）</button>
              <button disabled={busy} onClick={() => record({ is_correct: true, struggled: true }, "吃力 → Hard")}
                className="w-full py-2 bg-amber-50 text-amber-700 border border-amber-200 rounded-lg text-sm">做对了，但有点吃力</button>
              <button disabled={busy} onClick={() => record({ is_correct: false }, "没做出 → Again（记忆重置）")}
                className="w-full py-2 bg-red-50 text-red-700 border border-red-200 rounded-lg text-sm">没做出来</button>
            </div>
          )}

          {phase === "revealed" && (
            <div className="space-y-3">
              <div className="text-xs text-slate-500">{ratingLabel}</div>
              <div className="rounded-lg bg-slate-50 border border-slate-100 px-3 py-2">
                <div className="text-xs font-semibold text-slate-500 mb-1">参考答案</div>
                <MathText className="block text-sm text-slate-800 whitespace-pre-wrap">{cur.variant_answer}</MathText>
              </div>
              <button onClick={next} className="w-full py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium">
                {idx + 1 < items.length ? "下一题" : "完成"}
              </button>
            </div>
          )}
        </div>
      ) : null}
    </div>
  )
}
