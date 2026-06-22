import { KU_TYPE_META } from "../types"

export function KUTypeTag({ kuType }: { kuType: string }) {
  const meta = KU_TYPE_META[kuType] ?? { label: kuType, color: "text-gray-600", bg: "bg-gray-100" }
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ${meta.bg} ${meta.color}`}>
      {meta.label}
    </span>
  )
}
