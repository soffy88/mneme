import { useEffect, useState } from "react"
import { getParentReport, type DailyReport } from "../api"

/**
 * 家长学习日报（可一键复制转发微信）。
 * "微信日报"的 MVP：在 app 内生成一句话日报，家长复制后转发给亲友群/自己。
 */
export function DailyReportCard({ studentId, childName }: { studentId: string; childName?: string }) {
  const [r, setR] = useState<DailyReport | null>(null)
  const [err, setErr] = useState("")
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    getParentReport(studentId).then(setR).catch(e => setErr(e.message))
  }, [studentId])

  const copy = async () => {
    if (!r) return
    const text = `【${childName ?? "孩子"}】${r.report_text}`
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch { /* 剪贴板不可用时忽略 */ }
  }

  if (err) return <div className="text-xs text-red-500">{err}</div>
  if (!r) return <div className="text-xs text-slate-400">加载日报…</div>

  return (
    <div className="rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold text-emerald-700">今日日报</span>
        <button onClick={copy} className="text-[11px] px-2 py-0.5 rounded bg-white text-emerald-700 border border-emerald-200 hover:bg-emerald-100">
          {copied ? "已复制 ✓" : "复制转发微信"}
        </button>
      </div>
      <p className="text-xs text-slate-700 leading-relaxed">{r.report_text}</p>
    </div>
  )
}
