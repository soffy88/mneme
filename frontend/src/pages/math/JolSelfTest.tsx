import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { currentStudentId, postInteraction } from "../../api"
import { PageHeader } from "../../components/ui"

/**
 * JOL 自测校准（Judgment of Learning）：
 * 先预测把握 → 自己做 → 自评对错 → 对比预测与实际，给"高估/低估"反馈。
 * 训练元认知准度（知道自己哪里真会、哪里只是"感觉会"）。
 * 入口：/subjects/math/selftest?ku=<kc_id>&name=<显示名>
 */
type Phase = "predict" | "attempt" | "done"

export function JolSelfTest() {
  const [params] = useSearchParams()
  const kcId = params.get("ku") ?? ""
  const name = params.get("name") ?? "这个知识点"
  const studentId = currentStudentId()

  const [phase, setPhase] = useState<Phase>("predict")
  const [confidence, setConfidence] = useState(60)   // 0..100
  const [result, setResult] = useState<boolean | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")

  const submit = async (isCorrect: boolean) => {
    if (!studentId || busy) return
    setBusy(true); setErr("")
    try {
      await postInteraction({
        student_id: studentId, kc_id: kcId, is_correct: isCorrect,
        predicted_confidence: confidence / 100, source: "quick",
        struggled: confidence < 40,
      })
      setResult(isCorrect)
      setPhase("done")
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提交失败")
    } finally {
      setBusy(false)
    }
  }

  if (!studentId) return <div className="p-6 text-sm text-slate-500">请先登录。</div>
  if (!kcId) return <div className="p-6 text-sm text-red-500">缺少知识点。</div>

  // 校准反馈：预测 vs 实际
  const feedback = (() => {
    if (result === null) return null
    const c = confidence / 100
    if (result && c < 0.4) return { tone: "green", msg: "你没把握却做对了——其实你比自己想的更稳，别低估自己。" }
    if (result) return { tone: "green", msg: "判断准确：有把握，也确实做对了。" }
    if (!result && c >= 0.7) return { tone: "red", msg: "你很有把握却做错了——这是高估（『感觉会』≠真会）。这个点要重练，别跳过。" }
    if (!result && c < 0.4) return { tone: "amber", msg: "判断准确：你也知道没把握。补一补就好。" }
    return { tone: "amber", msg: "有点高估——半懂状态最危险，回去把它弄透。" }
  })()

  return (
    <div className="max-w-xl mx-auto px-4 py-8">
      <PageHeader title={`自测 · ${name}`} subtitle={`先预测，再验证——练的是"知道自己会不会"的准度`} />
      {err && <div className="text-xs text-red-500 mb-3">{err}</div>}

      {phase === "predict" && (
        <div className="card p-5 space-y-4">
          <div className="text-sm text-slate-700">动手前先预测：你有多大把握把「{name}」做对？</div>
          <input type="range" min={0} max={100} step={5} value={confidence}
            onChange={e => setConfidence(Number(e.target.value))} className="w-full" />
          <div className="text-center text-2xl font-bold text-indigo-600">{confidence}%</div>
          <button onClick={() => setPhase("attempt")}
            className="w-full py-2.5 bg-indigo-600 text-white rounded-lg text-sm font-medium">
            记下预测，开始做题
          </button>
        </div>
      )}

      {phase === "attempt" && (
        <div className="card p-5 space-y-4">
          <div className="text-sm text-slate-700">现在在纸上把「{name}」自己做一遍（不要看讲解）。做完如实自评：</div>
          <div className="text-xs text-slate-400">你的预测把握：{confidence}%</div>
          <div className="flex gap-3">
            <button disabled={busy} onClick={() => submit(true)}
              className="flex-1 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium disabled:opacity-50">我做对了</button>
            <button disabled={busy} onClick={() => submit(false)}
              className="flex-1 py-2.5 bg-slate-200 text-slate-700 rounded-lg text-sm font-medium disabled:opacity-50">我做错了</button>
          </div>
        </div>
      )}

      {phase === "done" && feedback && (
        <div className={`rounded-xl p-5 border ${
          feedback.tone === "green" ? "bg-emerald-50 border-emerald-200"
          : feedback.tone === "red" ? "bg-red-50 border-red-200" : "bg-amber-50 border-amber-200"
        }`}>
          <div className="text-sm font-semibold text-slate-800 mb-1">
            预测 {confidence}% · 实际{result ? "做对" : "做错"}
          </div>
          <p className="text-sm text-slate-700">{feedback.msg}</p>
          <p className="text-xs text-slate-400 mt-3">已记录——成长档案里能看到你的"判断准度"随时间变化。</p>
        </div>
      )}
    </div>
  )
}
