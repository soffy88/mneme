import Link from "next/link";

// 学习导航。学生最常用的三件事（拍照问题 / 10分钟复习 / 做题记录）始终在前；
// 手机（<640px）上其余入口收进「更多」折叠菜单，避免导航折成好几行把内容挤下去；
// 平板/桌面（sm 及以上）照旧平铺。用原生 <details>，无需客户端 JS，每项 min-h-44px 可点。
const PRIMARY = [
  { href: "/ask", label: "拍照问题" },
  { href: "/review", label: "10分钟复习" },
  { href: "/history", label: "做题记录" },
];

const MORE = [
  { href: "/learn", label: "马上学" },
  { href: "/today", label: "今日计划" },
  { href: "/path", label: "学习路径" },
  { href: "/practice", label: "练习" },
  { href: "/research", label: "研究" },
  { href: "/memory", label: "记忆" },
  { href: "/memory-inspect", label: "我的记忆" },
  { href: "/notebook", label: "笔记本" },
  { href: "/cowriter", label: "协同写作" },
  { href: "/weak-areas", label: "薄弱点" },
  { href: "/progress", label: "学习进度" },
  { href: "/immersive", label: "沉浸学习" },
  { href: "/lab", label: "实验室" },
  { href: "/animate", label: "动画讲解" },
  { href: "/book", label: "教材" },
];

export function ProductNav() {
  return (
    <nav className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm" aria-label="学习导航">
      {PRIMARY.map((l) => (
        <Link key={l.href} href={l.href} className="inline-flex min-h-[44px] items-center font-semibold">
          {l.label}
        </Link>
      ))}
      {MORE.map((l) => (
        <Link key={l.href} href={l.href} className="hidden min-h-[44px] items-center sm:inline-flex">
          {l.label}
        </Link>
      ))}
      <details className="relative sm:hidden" data-testid="nav-more">
        <summary className="inline-flex min-h-[44px] cursor-pointer list-none items-center gap-1 [&::-webkit-details-marker]:hidden">
          更多 <span aria-hidden>▾</span>
        </summary>
        <div className="absolute right-0 z-50 mt-1 grid w-44 grid-cols-1 rounded-xl border bg-[var(--background,#fff)] p-1 shadow-lg">
          {MORE.map((l) => (
            <Link key={l.href} href={l.href} className="flex min-h-[44px] items-center rounded-lg px-3">
              {l.label}
            </Link>
          ))}
        </div>
      </details>
    </nav>
  );
}
