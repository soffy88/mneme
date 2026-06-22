import { useState } from "react"
import { login } from "../api"

export function LoginForm({ onLogin }: { onLogin: () => void }) {
  const [phone, setPhone] = useState("")
  const [code, setCode] = useState("")
  const [err, setErr] = useState("")
  const [loading, setLoading] = useState(false)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setErr("")
    setLoading(true)
    try {
      await login(phone, code)
      onLogin()
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "登录失败")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={submit} className="bg-white p-8 rounded-2xl shadow-md w-80 space-y-4">
        <h1 className="text-xl font-bold text-gray-800 text-center">学鉴 Mneme</h1>
        <p className="text-sm text-gray-500 text-center">测试：手机号随意，验证码 123456</p>
        <input
          value={phone} onChange={e => setPhone(e.target.value)}
          placeholder="手机号" required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <input
          value={code} onChange={e => setCode(e.target.value)}
          placeholder="验证码（测试: 123456）" required
          className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        {err && <p className="text-red-500 text-xs">{err}</p>}
        <button
          type="submit" disabled={loading}
          className="w-full bg-blue-600 text-white rounded-lg py-2.5 font-medium hover:bg-blue-700 disabled:opacity-50"
        >
          {loading ? "登录中..." : "登录"}
        </button>
      </form>
    </div>
  )
}
