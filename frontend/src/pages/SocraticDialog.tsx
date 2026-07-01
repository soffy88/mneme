import { useEffect, useRef, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { MathText } from "../components/MathText"
import {
  currentStudentId,
  startSocraticForKu,
  sendSocraticMessage,
  escapeSocratic,
  endSocratic,
} from "../api"

type Msg = { role: "ai" | "me"; text: string }

/**
 * 通用苏格拉底引导对话页（跨学科复用）。
 * 红线：不展示标准答案/完整步骤；逃生出口只给"思路提示"（后端 escape 返回非答案大纲）。
 * 入口：/subjects/:subject/socratic?ku=<ku_id>&name=<显示名>
 */
export function SocraticDialog() {
  const [params] = useSearchParams()
  const kuId = params.get("ku") ?? ""
  const kuName = params.get("name") ?? "知识点"
  const studentId = currentStudentId()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState("")
  const [ended, setEnded] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  const missingInfo = !kuId || !studentId

  // 启动会话
  useEffect(() => {
    if (missingInfo) return
    startSocraticForKu(kuId, studentId!)
      .then(s => {
        setSessionId(s.session_id)
        setMsgs([{ role: "ai", text: s.first_question }])
      })
      .catch(e => setErr(e.message))
  }, [kuId, studentId, missingInfo])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [msgs])

  const send = async () => {
    const text = input.trim()
    if (!text || !sessionId || busy || ended) return
    setInput("")
    setErr("")
    setMsgs(m => [...m, { role: "me", text }, { role: "ai", text: "" }])
    setBusy(true)
    try {
      await sendSocraticMessage(
        sessionId,
        text,
        delta => setMsgs(m => {
          const copy = [...m]
          copy[copy.length - 1] = { role: "ai", text: copy[copy.length - 1].text + delta }
          return copy
        }),
      )
    } catch (e) {
      setErr(e instanceof Error ? e.message : "发送失败")
    } finally {
      setBusy(false)
    }
  }

  const onEscape = async () => {
    if (!sessionId || busy) return
    setBusy(true)
    try {
      const r = await escapeSocratic(sessionId)
      setMsgs(m => [...m, { role: "ai", text: `💡 思路提示（非标准答案）：\n${r.outline.map((s, i) => `${i + 1}. ${s}`).join("\n")}` }])
    } catch (e) {
      setErr(e instanceof Error ? e.message : "获取提示失败")
    } finally {
      setBusy(false)
    }
  }

  const finish = async (outcome: string) => {
    if (!sessionId) return
    await endSocratic(sessionId, outcome).catch(() => {})
    setEnded(true)
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 flex flex-col" style={{ height: "calc(100vh - 56px)" }}>
      <div className="mb-3">
        <h1 className="text-lg font-bold text-slate-900">苏格拉底引导 · {kuName}</h1>
        <p className="text-xs text-slate-400">我只问，不给答案——一步步带你自己想通。</p>
      </div>

      {missingInfo && <div className="text-xs text-red-500 mb-2">缺少知识点或登录信息</div>}
      {err && <div className="text-xs text-red-500 mb-2">{err}</div>}

      <div ref={scrollRef} className="flex-1 overflow-y-auto space-y-3 pb-3">
        {msgs.map((m, i) => (
          <div key={i} className={`flex ${m.role === "me" ? "justify-end" : "justify-start"}`}>
            <div className={`max-w-[80%] px-3.5 py-2 rounded-2xl text-sm whitespace-pre-wrap ${
              m.role === "me" ? "bg-indigo-600 text-white" : "bg-white border border-slate-200 text-slate-800"
            }`}>
              {m.text ? <MathText>{m.text}</MathText> : <span className="text-slate-400">思考中…</span>}
            </div>
          </div>
        ))}
      </div>

      {ended ? (
        <div className="text-center text-sm text-slate-500 py-3">本次引导已结束 ✓</div>
      ) : (
        <div className="border-t border-slate-200 pt-3">
          <div className="flex gap-2 mb-2">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") send() }}
              disabled={busy || !sessionId}
              placeholder="说出你的想法…"
              className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-indigo-400 disabled:bg-slate-50"
            />
            <button
              onClick={send}
              disabled={busy || !sessionId || !input.trim()}
              className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium disabled:opacity-40"
            >
              发送
            </button>
          </div>
          <div className="flex gap-3 text-xs text-slate-400">
            <button onClick={onEscape} disabled={busy || !sessionId} className="hover:text-slate-600 disabled:opacity-40">
              💡 给点思路（逃生出口）
            </button>
            <button onClick={() => finish("success")} disabled={!sessionId} className="hover:text-emerald-600">想通了 ✓</button>
            <button onClick={() => finish("abandoned")} disabled={!sessionId} className="hover:text-slate-600">结束</button>
          </div>
        </div>
      )}
    </div>
  )
}
