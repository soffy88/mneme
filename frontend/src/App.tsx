import { useState, useEffect } from "react"
import { BrowserRouter, Routes, Route, Navigate, Link, useLocation } from "react-router-dom"
import { LoginForm } from "./components/LoginForm"
import { PhysicsHome } from "./pages/physics/PhysicsHome"
import { PhysicsLesson } from "./pages/physics/PhysicsLesson"
import { PhysicsPractice } from "./pages/physics/PhysicsPractice"
import { ForceAnalysisPage } from "./pages/physics/ForceAnalysisPage"
import { ChineseHome } from "./pages/chinese/ChineseHome"
import { ChineseLesson } from "./pages/chinese/ChineseLesson"
import { WenyanWordBook } from "./pages/chinese/WenyanWordBook"
import { MingpianRecitation } from "./pages/chinese/MingpianRecitation"
import { ChineseDict } from "./pages/chinese/ChineseDict"
import { MathHome } from "./pages/math/MathHome"
import { MathLesson } from "./pages/math/MathLesson"
import { MathDashboard } from "./pages/math/MathDashboard"
import { PaperUpload } from "./pages/math/PaperUpload"
import { ErrorJournal } from "./pages/math/ErrorJournal"
import { MathPractice } from "./pages/math/MathPractice"
import { JolSelfTest } from "./pages/math/JolSelfTest"
import { ReviewPractice } from "./pages/math/ReviewPractice"
import { SocraticDialog } from "./pages/SocraticDialog"
import { ParentHome } from "./pages/parent/ParentHome"
import { EnglishHome } from "./pages/english/EnglishHome"
import { EssayGuide } from "./pages/english/EssayGuide"
import { Today } from "./pages/Today"
import { Subjects } from "./pages/Subjects"
import { Mastery } from "./pages/Mastery"
import { BottomNav } from "./components/BottomNav"
import { currentRole } from "./api"

function Brand({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to} className="flex items-center gap-2 shrink-0">
      <span className="grid h-7 w-7 place-items-center rounded-lg bg-indigo-600 text-white text-sm font-bold">鉴</span>
      <span className="font-semibold text-slate-800 text-sm tracking-tight">{label}</span>
    </Link>
  )
}

function NavBar() {
  const role = currentRole()
  const logout = () => { localStorage.removeItem("mneme_token"); location.reload() }
  return (
    <nav className="sticky top-0 z-20 h-14 px-4 flex items-center gap-3 bg-white/85 backdrop-blur border-b border-slate-200/70">
      <Brand to={role === "parent" ? "/parent" : "/today"} label={role === "parent" ? "学鉴 · 家长端" : "学鉴"} />
      <div className="flex-1" />
      <button onClick={logout} className="text-xs text-slate-400 hover:text-slate-600">退出</button>
    </nav>
  )
}

function Layout({ children, bottomNav }: { children: React.ReactNode; bottomNav?: boolean }) {
  const loc = useLocation()
  // 全屏对话流（苏格拉底/受力分析）隐藏底部 tab，避免遮挡输入框
  const focused = /\/socratic|force-analysis/.test(loc.pathname)
  const showNav = bottomNav && !focused
  return (
    <div className="min-h-screen bg-slate-50">
      <NavBar />
      <main className={showNav ? "pb-20" : ""}>{children}</main>
      {showNav && <BottomNav />}
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

  if (currentRole() === "parent") {
    return (
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/parent" element={<ParentHome />} />
            <Route path="*" element={<Navigate to="/parent" replace />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    )
  }

  return (
    <BrowserRouter>
      <Layout bottomNav>
        <Routes>
          <Route path="/" element={<Navigate to="/today" replace />} />
          <Route path="/today" element={<Today />} />
          <Route path="/subjects" element={<Subjects />} />
          <Route path="/mastery" element={<Mastery />} />
          <Route path="/subjects/english" element={<EnglishHome />} />
          <Route path="/subjects/english/essay" element={<EssayGuide />} />
          <Route path="/subjects/math" element={<MathHome />} />
          <Route path="/subjects/math/lesson" element={<MathLesson />} />
          <Route path="/subjects/math/dashboard" element={<MathDashboard />} />
          <Route path="/subjects/math/upload" element={<PaperUpload />} />
          <Route path="/subjects/math/errors" element={<ErrorJournal />} />
          <Route path="/subjects/math/practice" element={<MathPractice />} />
          <Route path="/subjects/math/selftest" element={<JolSelfTest />} />
          <Route path="/subjects/math/review" element={<ReviewPractice />} />
          <Route path="/subjects/:subject/socratic" element={<SocraticDialog />} />
          <Route path="/subjects/physics" element={<PhysicsHome />} />
          <Route path="/subjects/physics/lesson" element={<PhysicsLesson />} />
          <Route path="/subjects/physics/practice" element={<PhysicsPractice />} />
          <Route path="/subjects/physics/force-analysis" element={<ForceAnalysisPage />} />
          <Route path="/subjects/chinese" element={<ChineseHome />} />
          <Route path="/subjects/chinese/lesson" element={<ChineseLesson />} />
          <Route path="/subjects/chinese/wenyan-words" element={<WenyanWordBook />} />
          <Route path="/subjects/chinese/mingpian" element={<MingpianRecitation />} />
          <Route path="/subjects/chinese/dict" element={<ChineseDict />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  )
}
