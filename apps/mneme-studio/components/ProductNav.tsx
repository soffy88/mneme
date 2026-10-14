import Link from "next/link";

// 学习导航。学生最常用的三件事（拍照提问 / 复习 / 记录）排在最前，其余保留。
// 每个链接 min-h-44px：手机上可点，不依赖 hover。
export function ProductNav() {
  return (
    <nav className="flex flex-wrap gap-x-4 gap-y-1 text-sm" aria-label="学习导航">
      <Link href="/ask" className="inline-flex min-h-[44px] items-center font-semibold">拍照问题</Link>
      <Link href="/review" className="inline-flex min-h-[44px] items-center font-semibold">10分钟复习</Link>
      <Link href="/history" className="inline-flex min-h-[44px] items-center font-semibold">做题记录</Link>
      <Link href="/learn" className="inline-flex min-h-[44px] items-center">Learn Now</Link>
      <Link href="/today" className="inline-flex min-h-[44px] items-center">Today</Link>
      <Link href="/path" className="inline-flex min-h-[44px] items-center">Path</Link>
      <Link href="/practice" className="inline-flex min-h-[44px] items-center">Practice</Link>
      <Link href="/research" className="inline-flex min-h-[44px] items-center">Research</Link>
      <Link href="/memory" className="inline-flex min-h-[44px] items-center">Memory</Link>
      <Link href="/memory-inspect" className="inline-flex min-h-[44px] items-center">My Memory</Link>
      <Link href="/notebook" className="inline-flex min-h-[44px] items-center">Notebook</Link>
      <Link href="/cowriter" className="inline-flex min-h-[44px] items-center">Co-Writer</Link>
      <Link href="/weak-areas" className="inline-flex min-h-[44px] items-center">Weak Areas</Link>
      <Link href="/progress" className="inline-flex min-h-[44px] items-center">Progress</Link>
      <Link href="/immersive" className="inline-flex min-h-[44px] items-center">Immersive</Link>
      <Link href="/lab" className="inline-flex min-h-[44px] items-center">Lab</Link>
      <Link href="/animate" className="inline-flex min-h-[44px] items-center">Animate</Link>
      <Link href="/book" className="inline-flex min-h-[44px] items-center">Book</Link>
    </nav>
  );
}
