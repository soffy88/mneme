import { useMemo, useState } from "react"
import { useNavigate } from "react-router-dom"
import type { KU } from "../api"
import { MathText } from "./MathText"

/**
 * 补救阶梯（对抗冷启动挫败 / 专家逆转效应）。
 * 四级脚手架，按掌握度自适应入口；学生可"要更多帮助"下移、"我会了"上移：
 *   0 看讲解(完整样例) → 1 抓重点(淡出) → 2 苏格拉底(只问不答) → 3 独立
 * 内容取自 KU.rich_content（"讲透"），无需新后端。
 */
const STAGES = [
  { key: "worked", label: "看讲解", hint: "完整样例，先看懂" },
  { key: "faded", label: "抓重点", hint: "只给要点，自己回忆方法" },
  { key: "socratic", label: "苏格拉底", hint: "只问不答，一步步想通" },
  { key: "independent", label: "独立", hint: "自己推一遍" },
] as const

function entryStage(mastery: number | null): number {
  const m = mastery ?? 0
  if (m < 0.4) return 0      // 薄弱→给完整样例
  if (m < 0.7) return 1      // 中等→给要点
  return 2                   // 较强→直接苏格拉底（专家逆转：少给脚手架）
}

function Section({ title, value, tone = "gray" }: { title: string; value?: string | string[]; tone?: "gray" | "amber" }) {
  if (!value || (Array.isArray(value) && value.length === 0)) return null
  const items = Array.isArray(value) ? value : [value]
  const cls = tone === "amber" ? "bg-amber-50 border-amber-200 text-amber-800" : "bg-white border-slate-100 text-slate-700"
  return (
    <div className={`rounded-lg border px-3 py-2 ${cls}`}>
      <div className="text-xs font-semibold text-slate-500 mb-1">{title}</div>
      {items.map((t, i) => <MathText key={i} className="block text-sm whitespace-pre-wrap leading-relaxed" >{t}</MathText>)}
    </div>
  )
}

export function RemediationLadder({ ku }: { ku: KU }) {
  const navigate = useNavigate()
  const [stage, setStage] = useState(() => entryStage(ku.p_mastery))
  const rc = ku.rich_content ?? {}

  const masteryPct = useMemo(() => (ku.p_mastery != null ? Math.round(ku.p_mastery * 100) : null), [ku.p_mastery])

  return (
    <div className="space-y-4">
      {/* 阶梯进度 */}
      <div className="flex items-center gap-1.5">
        {STAGES.map((s, i) => (
          <div key={s.key} className="flex-1">
            <div className={`h-1.5 rounded-full ${i <= stage ? "bg-indigo-500" : "bg-slate-200"}`} />
            <div className={`text-[10px] mt-1 text-center ${i === stage ? "text-indigo-700 font-medium" : "text-slate-400"}`}>{s.label}</div>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500">
        当前：<b className="text-slate-700">{STAGES[stage].label}</b> · {STAGES[stage].hint}
        {masteryPct != null && <span className="ml-2 text-slate-400">入口按你的掌握度 {masteryPct}% 自动选择</span>}
      </p>

      {/* 阶段内容 */}
      {stage === 0 && (
        <div className="space-y-2">
          <Section title="定义" value={rc.definition} />
          <Section title="直觉理解" value={rc.intuition} />
          <Section title="样例（含完整解法）" value={rc.examples ?? rc.steps} />
        </div>
      )}
      {stage === 1 && (
        <div className="space-y-2">
          <Section title="关键点（自己回忆方法，别看样例）" value={rc.key_points} />
          <Section title="⚠️ 常见易错" value={rc.common_mistakes} tone="amber" />
          <p className="text-xs text-slate-400">想不起来？点下面"要更多帮助"回到完整样例。</p>
        </div>
      )}
      {stage === 2 && (
        <div className="space-y-3">
          <div className="text-sm text-slate-700">不直接给答案——用追问带你自己想通这道知识点。</div>
          <button
            onClick={() => navigate(`/subjects/math/socratic?ku=${encodeURIComponent(ku.id)}&name=${encodeURIComponent(ku.name)}`)}
            className="px-4 py-2 bg-indigo-600 text-white rounded-lg text-sm font-medium"
          >
            💬 开始苏格拉底引导
          </button>
        </div>
      )}
      {stage === 3 && (
        <div className="space-y-3">
          <div className="text-sm text-slate-700">现在自己把「{ku.name}」从头推一遍——卡住了随时退回上一级。</div>
          <Section title="自检：这些坑别踩" value={rc.common_mistakes} tone="amber" />
          <button
            onClick={() => navigate(`/subjects/math/selftest?ku=${encodeURIComponent(ku.id)}&name=${encodeURIComponent(ku.name)}`)}
            className="px-4 py-2 bg-emerald-600 text-white rounded-lg text-sm font-medium"
          >
            🎯 去自测（先预测把握，再验证）
          </button>
        </div>
      )}

      {/* 阶梯控制（desirable difficulty：可上可下） */}
      <div className="flex items-center justify-between pt-2 border-t border-slate-100">
        <button
          onClick={() => setStage(s => Math.max(0, s - 1))}
          disabled={stage === 0}
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-40"
        >
          ↓ 要更多帮助
        </button>
        <button
          onClick={() => setStage(s => Math.min(STAGES.length - 1, s + 1))}
          disabled={stage === STAGES.length - 1}
          className="text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-40"
        >
          我会了，少给点 ↑
        </button>
      </div>
    </div>
  )
}
