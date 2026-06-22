import { MASTERY_COLOR } from "../types"

export function MasteryDot({ color, mastery }: { color: string | null; mastery: number | null }) {
  const cls = color ? (MASTERY_COLOR[color] ?? "bg-gray-300") : "bg-gray-200"
  const pct = mastery != null ? `${Math.round(mastery * 100)}%` : "未学"
  return (
    <span className="flex items-center gap-1 text-xs text-gray-500">
      <span className={`w-2.5 h-2.5 rounded-full ${cls} inline-block`} />
      {pct}
    </span>
  )
}
