import { useState, useRef, useEffect } from "react"
import { Link } from "react-router-dom"

const BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000"

interface Msg { role: "user" | "assistant"; text: string }

export function ForceAnalysisPage() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [scenario, setScenario] = useState("")
  const [msgs, setMsgs] = useState<Msg[]>([])
  const [input, setInput] = useState("")
  const [starting, setStarting] = useState(false)
  const [streaming, setStreaming] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }) }, [msgs])

  const token = localStorage.getItem("mneme_token") ?? ""

  const startSession = async () => {
    if (!scenario.trim()) return
    setStarting(true)
    try {
      const res = await fetch(`${BASE}/v1/physics/force-analysis/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ scenario }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail)
      setSessionId(data.session_id)
      setMsgs([{ role: "assistant", text: data.first_message }])
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "启动失败")
    } finally {
      setStarting(false)
    }
  }

  const sendMessage = async () => {
    if (!input.trim() || !sessionId || streaming) return
    const userMsg = input.trim()
    setInput("")
    setMsgs(m => [...m, { role: "user", text: userMsg }])
    setStreaming(true)
    let buf = ""
    try {
      const res = await fetch(`${BASE}/v1/physics/force-analysis/message`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ session_id: sessionId, message: userMsg }),
      })
      const reader = res.body?.getReader()
      const dec = new TextDecoder()
      setMsgs(m => [...m, { role: "assistant", text: "" }])
      while (reader) {
        const { done, value } = await reader.read()
        if (done) break
        const chunk = dec.decode(value)
        for (const line of chunk.split("\n")) {
          if (line.startsWith("data: ")) {
            try {
              const d = JSON.parse(line.slice(6))
              if (d.content) {
                buf += d.content
                setMsgs(m => [...m.slice(0, -1), { role: "assistant", text: buf }])
              }
            } catch { /* skip malformed */ }
          }
        }
      }
    } catch (e: unknown) {
      setMsgs(m => [...m, { role: "assistant", text: "⚠️ 连接中断，请重试" }])
    } finally {
      setStreaming(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto px-4 py-6 flex flex-col h-screen">
      <div className="flex items-center gap-2 mb-4 text-sm text-gray-500">
        <Link to="/subjects/physics" className="hover:text-blue-600">物理</Link>
        <span>›</span>
        <span>受力分析引导</span>
      </div>

      <h1 className="text-lg font-bold text-gray-900 mb-4">⚡ 受力分析苏格拉底引导</h1>

      {!sessionId ? (
        <div className="space-y-4">
          <p className="text-sm text-gray-500">描述一个力学情景（如：一个木块在斜面上静止，斜面倾角30°），AI 将一步步引导你分析所有力。</p>
          <textarea
            value={scenario}
            onChange={e => setScenario(e.target.value)}
            placeholder="例如：一个质量为2kg的木块放在倾角30°的光滑斜面上，由一根平行于斜面的绳子拉住，绳子另一端固定在墙上。"
            rows={4}
            className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
          />
          <button
            onClick={startSession}
            disabled={starting || !scenario.trim()}
            className="w-full bg-purple-600 text-white rounded-lg py-2.5 font-medium hover:bg-purple-700 disabled:opacity-50"
          >
            {starting ? "正在启动..." : "开始受力分析"}
          </button>
        </div>
      ) : (
        <>
          <div className="flex-1 overflow-y-auto space-y-4 pb-4">
            {msgs.map((m, i) => (
              <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap ${
                  m.role === "user"
                    ? "bg-purple-600 text-white rounded-br-sm"
                    : "bg-white border border-gray-200 text-gray-800 rounded-bl-sm"
                }`}>
                  {m.text || (streaming ? "▋" : "")}
                </div>
              </div>
            ))}
            <div ref={bottomRef} />
          </div>
          <div className="flex gap-2 pt-3 border-t border-gray-100">
            <input
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage()}
              placeholder="输入你的回答..."
              disabled={streaming}
              className="flex-1 border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-purple-500 disabled:bg-gray-50"
            />
            <button
              onClick={sendMessage}
              disabled={streaming || !input.trim()}
              className="px-4 py-2 bg-purple-600 text-white rounded-lg text-sm hover:bg-purple-700 disabled:opacity-50"
            >
              发送
            </button>
          </div>
        </>
      )}
    </div>
  )
}
