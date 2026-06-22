import { useState } from "react"
import type { KU } from "../api"
import { KUDetailPanel } from "./KUDetailPanel"

interface Props {
  clusterName: string
  kus: KU[]
  studentId?: string
  onSocratic?: (ku: KU) => void
  onPractice?: (ku: KU) => void
}

export function KCGroup({ clusterName, kus, studentId, onSocratic, onPractice }: Props) {
  const [open, setOpen] = useState(false)
  const masteredCount = kus.filter(k => (k.p_mastery ?? 0) >= 0.7).length
  const total = kus.length

  return (
    <div className="mb-3 rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3.5 hover:bg-gray-50 text-left"
      >
        <span className="text-lg">{open ? "▾" : "▸"}</span>
        <span className="flex-1 font-semibold text-gray-800">{clusterName}</span>
        <span className="text-xs text-gray-500">{masteredCount}/{total} 已掌握</span>
        {/* 进度条 */}
        <div className="w-20 h-1.5 bg-gray-200 rounded-full overflow-hidden">
          <div
            className="h-full bg-green-500 rounded-full transition-all"
            style={{ width: `${total ? (masteredCount / total) * 100 : 0}%` }}
          />
        </div>
      </button>
      {open && (
        <div className="px-3 pb-3 space-y-2 border-t border-gray-100 pt-2">
          {kus.map(ku => (
            <KUDetailPanel
              key={ku.id}
              ku={ku}
              studentId={studentId}
              onSocratic={onSocratic}
              onPractice={onPractice}
            />
          ))}
        </div>
      )}
    </div>
  )
}
