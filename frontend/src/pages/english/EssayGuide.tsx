import { useState } from "react"
import { essayGuide, type EssayGuideResult } from "../../api"
import { PageHeader } from "../../components/ui"

const TYPES = ["议论文", "记叙文", "应用文（书信/通知）", "看图作文"]
const GRADES = ["初一", "初二", "初三", "高一", "高二", "高三"]

/**
 * 英语作文引导：贴作文 → 按维度给引导问题（不替你改写）。单次调用 /v1/essay/guide。
 */
export function EssayGuide() {
  const [text, setText] = useState("")
  const [grade, setGrade] = useState("高一")
  const [type, setType] = useState(TYPES[0])
  const [res, setRes] = useState<EssayGuideResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState("")

  const submit = async () => {
    if (!text.trim() || loading) return
    setErr(""); setLoading(true); setRes(null)
    try {
      setRes(await essayGuide(text.trim(), grade, type))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "批改失败")
    } finally {
      setLoading(false)
    }
  }

  const rubricText = res && res.rubric_scores
    ? (typeof res.rubric_scores === "string" ? res.rubric_scores : JSON.stringify(res.rubric_scores, null, 2))
    : ""

  return (
    <div className="max-w-2xl mx-auto px-4 py-6">
      <PageHeader title="英语作文引导" subtitle="只给引导问题，不替你改写——你自己改一遍，长得才牢。" />

      <div className="card p-4 space-y-3">
        <div className="flex gap-3">
          <select value={grade} onChange={e => setGrade(e.target.value)}
            className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
            {GRADES.map(g => <option key={g} value={g}>{g}</option>)}
          </select>
          <select value={type} onChange={e => setType(e.target.value)}
            className="flex-1 border border-slate-200 rounded-lg px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50">
            {TYPES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <textarea
          value={text} onChange={e => setText(e.target.value)}
          rows={8} placeholder="Paste your English essay here…"
          className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 resize-none"
        />
        {err && <p className="text-red-500 text-xs">{err}</p>}
        <button
          onClick={submit} disabled={loading || !text.trim()}
          className="w-full bg-indigo-600 text-white rounded-lg py-2.5 font-medium hover:bg-indigo-700 active:bg-indigo-800 transition-colors disabled:opacity-50"
        >
          {loading ? "引导生成中…" : "获取引导问题"}
        </button>
      </div>

      {res && (
        <div className="card p-4 mt-4 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-700 mb-2">引导问题（自己想，自己改）</h3>
            {res.guidance_questions?.length ? (
              <ol className="list-decimal list-inside space-y-1 text-sm text-slate-700">
                {res.guidance_questions.map((q, i) => <li key={i}>{q}</li>)}
              </ol>
            ) : <p className="text-sm text-slate-400">（无更多引导问题——这篇已比较完整）</p>}
          </div>
          {rubricText && (
            <details className="text-xs text-slate-500">
              <summary className="cursor-pointer text-slate-600 font-medium">分维度反馈</summary>
              <pre className="mt-2 whitespace-pre-wrap bg-slate-50 rounded-lg p-3">{rubricText}</pre>
            </details>
          )}
          {res.is_completed && <p className="text-xs text-emerald-600">✓ 这篇已达成主要要求</p>}
        </div>
      )}
    </div>
  )
}
