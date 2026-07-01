import { useState } from "react"
import { currentStudentId, uploadPaper, type PaperFindings } from "../../api"
import { PageHeader } from "../../components/ui"

/**
 * 试卷上传（冷启动钩子）。上传一张卷 → OCR+批改 → 驱动 BKT/FSRS → 返回错题概览。
 * 数据来自 POST /v1/papers/upload?student_id=（multipart）→ analyze_paper findings。
 */
export function PaperUpload() {
  const studentId = currentStudentId()
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [result, setResult] = useState<PaperFindings | null>(null)

  const submit = async () => {
    if (!file || !studentId || busy) return
    setBusy(true); setErr(""); setResult(null)
    try {
      setResult(await uploadPaper(studentId, file))
    } catch (e) {
      setErr(e instanceof Error ? e.message : "上传失败")
    } finally {
      setBusy(false)
    }
  }

  if (!studentId) return <div className="p-6 text-sm text-slate-500">请先登录后上传试卷。</div>

  return (
    <div className="max-w-2xl mx-auto px-4 py-8">
      <PageHeader title="上传数学试卷" subtitle="拍一张卷传上来——系统会识别、批改，并把错题接入你的认知档案。" />

      <div className="card p-5">
        <label className="block">
          <span className="text-sm text-slate-600">选择试卷图片</span>
          <input
            type="file"
            accept="image/*"
            onChange={e => setFile(e.target.files?.[0] ?? null)}
            className="mt-2 block w-full text-sm text-slate-500 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-indigo-50 file:text-indigo-700 hover:file:bg-indigo-100"
          />
        </label>
        <button
          onClick={submit}
          disabled={!file || busy}
          className="mt-4 px-5 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium disabled:opacity-40"
        >
          {busy ? "识别批改中…（约 1 分钟）" : "上传并分析"}
        </button>
        {err && <div className="text-xs text-red-500 mt-3">{err}</div>}
      </div>

      {result && (
        <div className="mt-6 bg-emerald-50 rounded-xl p-5 border border-emerald-200">
          <h2 className="text-sm font-semibold text-emerald-800 mb-3">分析完成</h2>
          <div className="flex gap-6 text-sm text-slate-700 mb-4">
            <span>共 <b>{result.total_questions}</b> 题</span>
            <span className="text-emerald-600">对 <b>{result.correct_count}</b></span>
            <span className="text-red-600">错 <b>{result.wrong_count}</b></span>
          </div>
          {result.wrong_count > 0 && (
            <div className="space-y-1.5">
              <div className="text-xs text-slate-500 mb-1">错题涉及的知识点：</div>
              {result.wrong_questions.map((w, i) => (
                <div key={i} className="text-xs text-slate-600 bg-white rounded px-2 py-1 border border-slate-100">
                  {(w.kc_ids ?? []).join("、") || "未标注知识点"}
                  {w.error_type && <span className="ml-2 text-amber-600">· {String(w.error_type)}</span>}
                </div>
              ))}
            </div>
          )}
          <p className="text-xs text-emerald-700 mt-4">错题已进入「成长档案」与「今日计划」，会按遗忘曲线安排复习。</p>
        </div>
      )}
    </div>
  )
}
