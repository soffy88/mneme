export const CHINESE_KU_TYPE_META: Record<string, { label: string; color: string; bg: string; track: "积累" | "鉴赏" | "表达" }> = {
  wenyan_word:     { label: "文言词语", color: "text-amber-700",   bg: "bg-amber-100",   track: "积累" },
  wenyan_syntax:   { label: "文言句式", color: "text-yellow-700",  bg: "bg-yellow-100",  track: "积累" },
  mingpian:        { label: "名篇名句", color: "text-lime-700",    bg: "bg-lime-100",    track: "积累" },
  chengyu:         { label: "成语典故", color: "text-green-700",   bg: "bg-green-100",   track: "积累" },
  wenhua_changshi: { label: "文化常识", color: "text-teal-700",    bg: "bg-teal-100",    track: "积累" },
  xinxi_yuedu:     { label: "信息阅读", color: "text-indigo-700",  bg: "bg-indigo-100",  track: "鉴赏" },
  xiaoshuo_yuedu:  { label: "小说阅读", color: "text-indigo-700",  bg: "bg-indigo-100",  track: "鉴赏" },
  sanwen_yuedu:    { label: "散文阅读", color: "text-indigo-700",  bg: "bg-indigo-100",  track: "鉴赏" },
  wenyan_yuedu:    { label: "文言阅读", color: "text-indigo-700",    bg: "bg-indigo-100",    track: "鉴赏" },
  shici_jianshang: { label: "诗词鉴赏", color: "text-sky-700",     bg: "bg-sky-100",     track: "鉴赏" },
  xiezuo:          { label: "写作方法", color: "text-rose-700",    bg: "bg-rose-100",    track: "表达" },
  kouyu_jiaoji:    { label: "口语交际", color: "text-orange-700",  bg: "bg-orange-100",  track: "表达" },
  goutong_chushi:  { label: "沟通处世", color: "text-red-700",     bg: "bg-red-100",     track: "表达" },
}

export const CHINESE_TRACKS = ["积累", "鉴赏", "表达"] as const
export type ChineseTrack = (typeof CHINESE_TRACKS)[number]

export const TRACK_STYLE: Record<ChineseTrack, { color: string; bg: string; activeBg: string }> = {
  积累: { color: "text-amber-700",  bg: "bg-amber-50",  activeBg: "bg-amber-100 border-amber-400" },
  鉴赏: { color: "text-indigo-700", bg: "bg-indigo-50", activeBg: "bg-indigo-100 border-indigo-400" },
  表达: { color: "text-rose-700",   bg: "bg-rose-50",   activeBg: "bg-rose-100 border-rose-400" },
}

export interface Chinese002Desc {
  knowledge_kind: string
  know_what: string
  know_how: string
  know_why: string
  example: string
  source: string
  track: string
  wenyan: string  // 文言额外信息
}

export function parseChinese002Desc(raw: string | null): Chinese002Desc {
  const out: Chinese002Desc = { knowledge_kind: "", know_what: "", know_how: "", know_why: "", example: "", source: "", track: "", wenyan: "" }
  if (!raw) return out
  for (const line of raw.split("\n")) {
    const l = line.trim()
    if (l.startsWith("[") && l.endsWith("]") && !l.startsWith("[文言]")) out.knowledge_kind = l.slice(1, -1)
    else if (l.startsWith("know-what:")) out.know_what = l.slice(10).trim()
    else if (l.startsWith("know-how:"))  out.know_how  = l.slice(9).trim()
    else if (l.startsWith("know-why:"))  out.know_why  = l.slice(9).trim()
    else if (l.startsWith("实例:"))       out.example   = l.slice(3).trim()
    else if (l.startsWith("来源:"))       out.source    = l.slice(3).trim()
    else if (l.startsWith("轨道:"))       out.track     = l.slice(3).trim()
    else if (l.startsWith("[文言]:"))     out.wenyan    = l.slice(5).trim()
  }
  return out
}

// 数学知识类型（ku_type 实际取值：concept / formula / method，少量 model；
// theorem/definition/property 作为细分别名优雅兜底）
export const MATH_KU_TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  concept:    { label: "概念", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  theorem:    { label: "定理", color: "text-violet-700",  bg: "bg-violet-100"  },
  formula:    { label: "公式", color: "text-rose-700",    bg: "bg-rose-100"    },
  method:     { label: "方法", color: "text-teal-700",    bg: "bg-teal-100"    },
  model:      { label: "模型", color: "text-emerald-700", bg: "bg-emerald-100" },
  definition: { label: "定义", color: "text-sky-700",     bg: "bg-sky-100"     },
  property:   { label: "性质", color: "text-amber-700",   bg: "bg-amber-100"   },
}

export const KU_TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  // 物理
  physical_concept: { label: "概念", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  physical_law:     { label: "规律", color: "text-violet-700",  bg: "bg-violet-100"  },
  physical_model:   { label: "模型", color: "text-emerald-700", bg: "bg-emerald-100" },
  experiment:       { label: "实验", color: "text-amber-700",   bg: "bg-amber-100"   },
  method:           { label: "方法", color: "text-teal-700",    bg: "bg-teal-100"    },
  formula:          { label: "公式", color: "text-rose-700",    bg: "bg-rose-100"    },
  // 数学（KUTypeTag 用 KU_TYPE_META 渲染，故此处需覆盖数学 ku_type）
  concept:          { label: "概念", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  theorem:          { label: "定理", color: "text-violet-700",  bg: "bg-violet-100"  },
  model:            { label: "模型", color: "text-emerald-700", bg: "bg-emerald-100" },
  definition:       { label: "定义", color: "text-sky-700",     bg: "bg-sky-100"     },
  property:         { label: "性质", color: "text-amber-700",   bg: "bg-amber-100"   },
  // 语文 (mirrors CHINESE_KU_TYPE_META for KUTypeTag compatibility)
  wenyan_word:     { label: "文言词语", color: "text-amber-700",   bg: "bg-amber-100"   },
  wenyan_syntax:   { label: "文言句式", color: "text-yellow-700",  bg: "bg-yellow-100"  },
  mingpian:        { label: "名篇名句", color: "text-lime-700",    bg: "bg-lime-100"    },
  chengyu:         { label: "成语典故", color: "text-green-700",   bg: "bg-green-100"   },
  wenhua_changshi: { label: "文化常识", color: "text-teal-700",    bg: "bg-teal-100"    },
  xinxi_yuedu:     { label: "信息阅读", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  xiaoshuo_yuedu:  { label: "小说阅读", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  sanwen_yuedu:    { label: "散文阅读", color: "text-indigo-700",  bg: "bg-indigo-100"  },
  wenyan_yuedu:    { label: "文言阅读", color: "text-indigo-700",    bg: "bg-indigo-100"    },
  shici_jianshang: { label: "诗词鉴赏", color: "text-sky-700",     bg: "bg-sky-100"     },
  xiezuo:          { label: "写作方法", color: "text-rose-700",    bg: "bg-rose-100"    },
  kouyu_jiaoji:    { label: "口语交际", color: "text-orange-700",  bg: "bg-orange-100"  },
  goutong_chushi:  { label: "沟通处世", color: "text-red-700",     bg: "bg-red-100"     },
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
