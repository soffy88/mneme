import Link from "next/link";

export function ProductNav() {
  return (
    <nav className="flex flex-wrap gap-3 text-sm" aria-label="学习导航">
      <Link href="/learn" className="font-semibold">Learn Now</Link>
      <Link href="/today">Today</Link>
      <Link href="/path">Path</Link>
      <Link href="/practice">Practice</Link>
      <Link href="/memory">Memory</Link>
      <Link href="/memory-inspect">My Memory</Link>
      <Link href="/notebook">Notebook</Link>
      <Link href="/cowriter">Co-Writer</Link>
      <Link href="/weak-areas">Weak Areas</Link>
      <Link href="/progress">Progress</Link>
      <Link href="/immersive">Immersive</Link>
      <Link href="/lab">Lab</Link>
    </nav>
  );
}
