import Link from "next/link";

export function ProductNav() {
  return (
    <nav className="flex flex-wrap gap-3 text-sm" aria-label="学习导航">
      <Link href="/learn" className="font-semibold">Learn Now</Link>
      <Link href="/today">Today</Link>
      <Link href="/memory">Memory</Link>
      <Link href="/weak-areas">Weak Areas</Link>
      <Link href="/progress">Progress</Link>
    </nav>
  );
}
