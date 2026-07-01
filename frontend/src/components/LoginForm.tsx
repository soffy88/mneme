import { useState } from "react"
import { login, registerStudent } from "../api"

export function LoginForm({ onLogin }: { onLogin: () => void }) {
  const [mode, setMode] = useState<"login" | "register">("login")
  const [phone, setPhone] = useState("")
  const [code, setCode] = useState("")
  const [name, setName] = useState("")
  const [grade, setGrade] = useState("高一")
  const [err, setErr] = useState("")
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr("")
    setLoading(true)
    try {
      if (mode === "login") {
        await login(phone, code)
      } else {
        await registerStudent(phone, code, name.trim() || `同学${phone.slice(-4)}`, { grade })
      }
      onLogin()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : (mode === "login" ? "登录失败" : "注册失败")
      // 登录时遇"用户不存在"，引导去注册
      if (mode === "login" && /不存在|注册|not found/i.test(msg)) {
        setMode("register")
        setErr("该手机号还没注册，填个昵称即可注册")
      } else {
        setErr(msg)
      }
    } finally {
      setLoading(false)
    }
  }

  const GRADES = ["初一", "初二", "初三", "高一", "高二", "高三"]

  return (
    <div className="min-h-screen flex items-center justify-center px-4 bg-gradient-to-b from-slate-50 to-indigo-50/40">
      <div className="w-full max-w-sm">
        <div className="flex flex-col items-center mb-6">
          <span className="grid h-12 w-12 place-items-center rounded-2xl bg-indigo-600 text-white text-xl font-bold shadow-soft">鉴</span>
          <h1 className="mt-3 text-2xl font-bold text-slate-900 tracking-tight">学鉴 Mneme</h1>
          <p className="mt-1 text-sm text-slate-500">一面照见你学习轨迹的镜子</p>
        </div>

        {/* 登录/注册切换 */}
        <div className="flex bg-slate-100 rounded-lg p-0.5 mb-3 text-sm">
          {(["login", "register"] as const).map(m => (
            <button
              key={m}
              type="button"
              onClick={() => { setMode(m); setErr("") }}
              className={`flex-1 py-1.5 rounded-md font-medium transition-colors ${
                mode === m ? "bg-white text-indigo-700 shadow-sm" : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {m === "login" ? "登录" : "注册"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} className="bg-white p-6 rounded-2xl border border-slate-100 shadow-soft space-y-3">
          <input
            value={phone} onChange={e => setPhone(e.target.value)}
            placeholder="手机号" required inputMode="tel"
            className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-400"
          />
          <input
            value={code} onChange={e => setCode(e.target.value)}
            placeholder="验证码" required
            className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-400"
          />
          {mode === "register" && (
            <>
              <input
                value={name} onChange={e => setName(e.target.value)}
                placeholder="昵称（如：小明）"
                className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-400"
              />
              <select
                value={grade} onChange={e => setGrade(e.target.value)}
                className="w-full border border-slate-200 rounded-lg px-3.5 py-2.5 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500/50 focus:border-indigo-400"
              >
                {GRADES.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </>
          )}
          {err && <p className="text-amber-600 text-xs">{err}</p>}
          <button
            type="submit" disabled={loading}
            className="w-full bg-indigo-600 text-white rounded-lg py-2.5 font-medium hover:bg-indigo-700 active:bg-indigo-800 transition-colors disabled:opacity-50"
          >
            {loading ? "处理中…" : mode === "login" ? "登录" : "注册并进入"}
          </button>
          <p className="text-xs text-slate-400 text-center pt-1">
            测试：手机号随意，验证码 <span className="font-medium text-slate-500">123456</span>
            {mode === "login" ? "；首次用请点上方「注册」" : ""}
          </p>
        </form>
      </div>
    </div>
  )
}
