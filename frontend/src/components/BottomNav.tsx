import { Link, useLocation } from "react-router-dom"

/**
 * 移动优先的底部 tab 栏：今日 / 学科 / 掌握度。
 * 学生端全局显示；家长端不显示（家长走自己的 /parent）。
 */
const TABS = [
  { to: "/today", label: "今日", icon: "📅" },
  { to: "/subjects", label: "学科", icon: "📚" },
  { to: "/mastery", label: "掌握度", icon: "🪞" },
]

export function BottomNav() {
  const loc = useLocation()
  return (
    <nav className="fixed bottom-0 inset-x-0 z-30 h-16 flex bg-white/90 backdrop-blur border-t border-slate-200/70">
      {TABS.map(t => {
        const active = t.to === "/subjects"
          ? loc.pathname.startsWith("/subjects")
          : loc.pathname === t.to
        return (
          <Link
            key={t.to}
            to={t.to}
            className={`flex-1 flex flex-col items-center justify-center gap-0.5 text-xs transition-colors ${
              active ? "text-indigo-600" : "text-slate-400 hover:text-slate-600"
            }`}
          >
            <span className="text-lg leading-none">{t.icon}</span>
            <span className={active ? "font-medium" : ""}>{t.label}</span>
          </Link>
        )
      })}
    </nav>
  )
}
