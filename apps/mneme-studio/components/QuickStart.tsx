import Link from "next/link";

// 学生首页的三个大按钮：拍照提问 / 10分钟复习 / 做题记录。
// 大卡片 + emoji，手机上单手可点（min-h 44px 以上），不依赖 hover。
const ACTIONS = [
  { href: "/ask", emoji: "📷", label: "拍照问题目", sub: "拍下来，马上给你思路和步骤" },
  { href: "/review", emoji: "⏱️", label: "10分钟复习", sub: "把错题巩固一遍" },
  { href: "/history", emoji: "📒", label: "做题记录", sub: "看看自己做过哪些题" },
];

export function QuickStart() {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      {ACTIONS.map((a) => (
        <Link
          key={a.href}
          href={a.href}
          className="flex min-h-[96px] flex-col justify-center gap-1 rounded-[var(--card-radius,1rem)] border border-[var(--border)] bg-[var(--card)] p-4 text-left active:scale-[0.99]"
        >
          <span className="text-3xl" aria-hidden>{a.emoji}</span>
          <span className="text-lg font-semibold">{a.label}</span>
          <span className="text-sm text-[var(--muted-foreground,#888)]">{a.sub}</span>
        </Link>
      ))}
    </div>
  );
}
