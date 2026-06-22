export const KU_TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  physical_concept: { label: "概念", color: "text-blue-700",   bg: "bg-blue-100"   },
  physical_law:     { label: "规律", color: "text-purple-700", bg: "bg-purple-100" },
  physical_model:   { label: "模型", color: "text-emerald-700",bg: "bg-emerald-100"},
  experiment:       { label: "实验", color: "text-amber-700",  bg: "bg-amber-100"  },
  method:           { label: "方法", color: "text-teal-700",   bg: "bg-teal-100"   },
  formula:          { label: "公式", color: "text-rose-700",   bg: "bg-rose-100"   },
}

export interface ParsedDesc {
  core: string
  conditions: string
  experiment: {
    purpose: string
    principle: string
    instruments: string
    key_steps: string
    data_method: string
  } | null
}

export function parseDescription(raw: string | null): ParsedDesc {
  if (!raw) return { core: "", conditions: "", experiment: null }
  const lines = raw.split("\n")
  const coreLines: string[] = []
  let conditions = ""
  let expLine = ""
  for (const l of lines) {
    if (l.startsWith("【适用条件】")) conditions = l.slice(6)
    else if (l.startsWith("【实验】")) expLine = l.slice(4)
    else coreLines.push(l)
  }
  let experiment: ParsedDesc["experiment"] = null
  if (expLine) {
    const seg = (prefix: string) =>
      expLine.split("；").find(s => s.startsWith(prefix))?.slice(prefix.length) ?? ""
    experiment = {
      purpose:     seg("目的："),
      principle:   seg("原理："),
      instruments: seg("器材："),
      key_steps:   seg("步骤："),
      data_method: seg("数据处理："),
    }
  }
  return { core: coreLines.filter(Boolean).join("\n"), conditions, experiment }
}

export const MASTERY_COLOR: Record<string, string> = {
  red:    "bg-red-400",
  orange: "bg-orange-400",
  yellow: "bg-yellow-400",
  green:  "bg-green-500",
}
