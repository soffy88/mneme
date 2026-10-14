// 学生端显示用的小工具：学科代码 → 中文、时间按北京时间（Asia/Shanghai）渲染。
// 后端时间戳是 UTC ISO 串；不能依赖浏览器/容器本地时区（无头浏览器、SSR 都是 UTC）。

export const SUBJECT_LABELS: Record<string, string> = {
  math: "数学",
  chinese: "语文",
  english: "英语",
  physics: "物理",
  chemistry: "化学",
  biology: "生物",
  history: "历史",
  geography: "地理",
  politics: "政治",
  science: "科学",
  other: "其他",
};

/** 筛选下拉用：value 是后端存的学科代码，label 是中文。 */
export const SUBJECT_OPTIONS: { value: string; label: string }[] = [
  "math",
  "chinese",
  "english",
  "physics",
  "chemistry",
  "biology",
  "history",
  "geography",
  "politics",
  "other",
].map((value) => ({ value, label: SUBJECT_LABELS[value] }));

export function subjectLabel(subject: string | null | undefined): string {
  if (!subject) return "";
  const key = subject.trim().toLowerCase();
  return SUBJECT_LABELS[key] ?? subject;
}

export const DISPLAY_TZ = "Asia/Shanghai";

const PARTS_FMT = new Intl.DateTimeFormat("zh-CN", {
  timeZone: DISPLAY_TZ,
  year: "numeric",
  month: "numeric",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

function parts(d: Date): Record<string, string> {
  const out: Record<string, string> = {};
  for (const p of PARTS_FMT.formatToParts(d)) out[p.type] = p.value;
  return out;
}

function parseIso(iso: string): Date {
  // 无时区后缀的串按 UTC 解析（后端约定 UTC），避免被当成浏览器本地时间。
  const s = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  return new Date(s);
}

/** 北京时间：今年 →「10月14日 15:07」，跨年 →「2025年10月14日 15:07」。 */
export function formatWhen(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "";
  const d = parseIso(iso);
  if (Number.isNaN(d.getTime())) return "";
  const p = parts(d);
  const n = parts(now);
  const time = `${p.hour}:${p.minute}`;
  if (p.year === n.year) return `${p.month}月${p.day}日 ${time}`;
  return `${p.year}年${p.month}月${p.day}日 ${time}`;
}
