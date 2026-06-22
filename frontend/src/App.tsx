import { useState, useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from "react-router-dom"
import { LoginForm } from "./components/LoginForm"
import { PhysicsHome } from "./pages/physics/PhysicsHome"
import { PhysicsLesson } from "./pages/physics/PhysicsLesson"
import { PhysicsPractice } from "./pages/physics/PhysicsPractice"
import { ForceAnalysisPage } from "./pages/physics/ForceAnalysisPage"

function NavBar() {
  const loc = useLocation()
  const isPhysics = loc.pathname.startsWith("/subjects/physics")
  return (
    <nav className="bg-white border-b border-gray-200 px-4 py-2.5 flex items-center gap-4">
      <Link to="/" className="font-bold text-gray-800 text-sm">学鉴</Link>
      <div className="flex gap-1 text-sm">
        <Link
          to="/subjects/physics"
          className={`px-3 py-1.5 rounded-lg transition-colors ${
            isPhysics ? "bg-blue-100 text-blue-700 font-medium" : "text-gray-600 hover:bg-gray-100"
          }`}
        >
          物理
        </Link>
      </div>
      <div className="flex-1" />
      <button
        onClick={() => { localStorage.removeItem("mneme_token"); location.reload() }}
        className="text-xs text-gray-400 hover:text-gray-600"
      >
        退出
      </button>
    </nav>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-gray-50">
      <NavBar />
      <main>{children}</main>
    </div>
  )
}

export default function App() {
  const [authed, setAuthed] = useState(() => !!localStorage.getItem("mneme_token"))

  useEffect(() => {
    const handler = () => setAuthed(!!localStorage.getItem("mneme_token"))
    window.addEventListener("storage", handler)
    return () => window.removeEventListener("storage", handler)
  }, [])

  if (!authed) return <LoginForm onLogin={() => setAuthed(true)} />

  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Navigate to="/subjects/physics" replace />} />
          <Route path="/subjects/physics" element={<PhysicsHome />} />
          <Route path="/subjects/physics/lesson" element={<PhysicsLesson />} />
          <Route path="/subjects/physics/practice" element={<PhysicsPractice />} />
          <Route path="/subjects/physics/force-analysis" element={<ForceAnalysisPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
