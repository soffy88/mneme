import type { ParsedDesc } from "../types"

export function ExperimentMeta({ exp }: { exp: NonNullable<ParsedDesc["experiment"]> }) {
  const rows = [
    { label: "实验目的", value: exp.purpose },
    { label: "实验原理", value: exp.principle },
    { label: "主要器材", value: exp.instruments },
    { label: "关键步骤", value: exp.key_steps },
    { label: "数据处理", value: exp.data_method },
  ].filter(r => r.value)

  return (
    <div className="mt-3 bg-amber-50 border border-amber-200 rounded-lg p-3">
      <div className="flex items-center gap-1.5 mb-2">
        <span className="text-amber-600">🔬</span>
        <span className="text-sm font-semibold text-amber-800">实验详情</span>
      </div>
      <dl className="space-y-1.5">
        {rows.map(r => (
          <div key={r.label} className="grid grid-cols-[5rem_1fr] gap-2 text-sm">
            <dt className="text-amber-700 font-medium shrink-0">{r.label}</dt>
            <dd className="text-slate-700">{r.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
