import { useState } from "react"
import type { KU } from "../api"
import { parseDescription } from "../types"
import { KUTypeTag } from "./KUTypeTag"
import { MasteryDot } from "./MasteryDot"
import { ExperimentMeta } from "./ExperimentMeta"
import { MathText } from "./MathText"
import { pdfUrl } from "../api"

interface Props {
  ku: KU
  studentId?: string
  onSocratic?: (ku: KU) => void
  onPractice?: (ku: KU) => void
}

export function KUDetailPanel({ ku, onSocratic, onPractice }: Props) {
  const [open, setOpen] = useState(false)
  const desc = parseDescription(ku.description)

  return (
    <div className="border border-slate-200 rounded-lg bg-white overflow-hidden">
      {/* 折叠行 */}
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-50 text-left"
      >
        <span className="text-slate-400 text-xs w-4">{open ? "▾" : "▸"}</span>
        <KUTypeTag kuType={ku.ku_type} />
        <span className="flex-1 text-sm font-medium text-slate-800">{ku.name}</span>
        <MasteryDot color={ku.mastery_color} mastery={ku.p_mastery} />
        <span className="text-xs text-slate-400">难度 {Math.round(ku.difficulty * 10)}/10</span>
      </button>

      {/* 展开详情 */}
      {open && (
        <div className="px-4 pb-4 border-t border-slate-100 bg-slate-50 space-y-3">
          {/* 核心描述 */}
          {desc.core && (
            <MathText className="block pt-3 text-sm text-slate-700 whitespace-pre-wrap">{desc.core}</MathText>
          )}

          {/* 适用条件 */}
          {desc.conditions && (
            <div className="flex gap-2 text-sm bg-amber-50 border border-amber-200 rounded px-3 py-2">
              <span className="text-amber-500 font-medium shrink-0">⚠ 适用条件</span>
              <MathText className="text-amber-800">{desc.conditions}</MathText>
            </div>
          )}

          {/* 实验 meta */}
          {desc.experiment && <ExperimentMeta exp={desc.experiment} />}

          {/* 前置 KU */}
          {ku.prerequisites && ku.prerequisites.length > 0 && (
            <div className="text-xs text-slate-500">
              <span className="font-medium">前置知识：</span>
              {ku.prerequisites.join(" → ")}
            </div>
          )}

          {/* 操作按钮 */}
          <div className="flex gap-2 flex-wrap pt-1">
            {ku.textbook_file_id && (
              <a
                href={pdfUrl(ku.textbook_file_id)}
                target="_blank"
                rel="noopener"
                className="px-3 py-1.5 text-xs rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200"
              >
                📖 查看教材原文
              </a>
            )}
            {onSocratic && (
              <button
                onClick={() => onSocratic(ku)}
                className="px-3 py-1.5 text-xs rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200"
              >
                💬 不懂问一问
              </button>
            )}
            {onPractice && (
              <button
                onClick={() => onPractice(ku)}
                className="px-3 py-1.5 text-xs rounded-md bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200"
              >
                ✏️ 做几道题
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
