"use client";

// /studio/history —— 做题记录（移动端优先）。
//
// 列表来自 /v1/questions/history（分页 + 筛选），详情来自 /v1/questions/history/{id}。
// 筛选条横向滚动，不撑破页面；详情在卡片内就地展开。

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { OButton, OCard, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { SUBJECT_OPTIONS, subjectLabel } from "@/lib/format";
import { MathText } from "@/components/MathText";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  addToWrongbook, fetchQuestionImageUrl, historyDetail, historyList, historySummary,
  type HistoryDetail, type HistoryItem, type HistoryResult, type HistorySummaryDay,
} from "@/lib/questions";

const RESULT_CHIPS: { label: string; value: HistoryResult | null }[] = [
  { label: "全部", value: null },
  { label: "做对", value: "correct" },
  { label: "做错", value: "wrong" },
  { label: "提问", value: "unknown" },
];


const SOURCES: { label: string; value: string }[] = [
  { label: "全部来源", value: "" },
  { label: "拍照提问", value: "ask" },
  { label: "练习", value: "practice" },
  { label: "小测", value: "quiz" },
  { label: "复习", value: "review" },
  { label: "对话", value: "chat" },
  { label: "其他", value: "other" },
];

const PAGE_SIZE = 20;

function beijingDayKey(value: string | Date): string {
  const date = value instanceof Date ? value : new Date(value);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? "00";
  return `${part("year")}-${part("month")}-${part("day")}`;
}

function beijingTime(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(new Date(value));
}

function historyDayTitle(dayKey: string): string {
  const todayKey = beijingDayKey(new Date());
  if (dayKey === todayKey) return "今天";
  const todayStart = new Date(`${todayKey}T00:00:00+08:00`);
  const yesterdayKey = beijingDayKey(new Date(todayStart.getTime() - 24 * 60 * 60 * 1000));
  if (dayKey === yesterdayKey) return "昨天";
  const [, month, day] = dayKey.split("-").map(Number);
  const date = new Date(`${dayKey}T12:00:00+08:00`);
  const weekday = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    weekday: "short",
  }).format(date).replace("星期", "").replace("周", "");
  return `${month}月${day}日 周${weekday}`;
}

function groupHistoryByDay(items: HistoryItem[]): { date: string; items: HistoryItem[] }[] {
  const groups = new Map<string, HistoryItem[]>();
  for (const item of items) {
    const date = beijingDayKey(item.created_at);
    const current = groups.get(date) ?? [];
    current.push(item);
    groups.set(date, current);
  }
  return Array.from(groups, ([date, dayItems]) => ({ date, items: dayItems }));
}


function resultIcon(isCorrect: boolean | null): string {
  if (isCorrect === true) return "✅";
  if (isCorrect === false) return "❌";
  return "❓";
}

/** 带 token 取题目图片 → object URL（token 绝不进 URL）。 */
function DetailImage({ recordId }: { recordId: string }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let obj: string | null = null;
    let alive = true;
    fetchQuestionImageUrl(recordId)
      .then((u) => {
        obj = u;
        if (alive) setUrl(u);
        else URL.revokeObjectURL(u);
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
      if (obj) URL.revokeObjectURL(obj);
    };
  }, [recordId]);

  if (failed) return <div className="text-sm text-[var(--muted-foreground,#888)]">（图片加载失败）</div>;
  if (!url) return <div className="text-sm text-[var(--muted-foreground,#888)]">图片加载中…</div>;
  return (
    // eslint-disable-next-line @next/next/no-img-element
    <img src={url} alt="题目图片" className="mx-auto max-h-[70vh] max-w-full w-auto rounded-lg border object-contain" />
  );
}

function HistoryThumbnail({ recordId }: { recordId: string }) {
  const [url, setUrl] = useState<string | null>(null);

  useEffect(() => {
    let objectUrl: string | null = null;
    let alive = true;
    fetchQuestionImageUrl(recordId)
      .then((nextUrl) => {
        objectUrl = nextUrl;
        if (alive) setUrl(nextUrl);
        else URL.revokeObjectURL(nextUrl);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [recordId]);

  if (!url) {
    return <span aria-label="图片缩略图加载中" className="h-12 w-12 shrink-0 rounded-lg bg-[var(--muted,#f3f3f3)]" />;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt="题目缩略图" className="h-12 w-12 shrink-0 rounded-lg object-cover" />;
}

const GRADER_LABELS: Record<string, string> = {
  kernel: "自动判分（精确计算）",
  exact: "自动判分",
  numeric: "自动判分",
  choice: "自动判分",
  self: "自己评",
  self_grade: "自己评",
  llm: "AI 判分",
  provider: "自动判分",
};

function graderLabel(g: string | null | undefined): string {
  if (!g) return "—";
  return GRADER_LABELS[g.toLowerCase()] ?? "自动判分";
}

/** 知识点编码（RENJIAO-G8-MATH-S-ku-二次根式的定义、cmm-math-g6-算术）→ 只留中文名。 */
function kpName(k: string): string {
  const zh = k.split("-").filter((p) => /[\u4e00-\u9fff]/.test(p)).join("-");
  return zh || k;
}

function DetailRow({ label, value }: { label: string; value: string | null }) {
  return (
    <div className="text-base">
      <span className="text-sm text-[var(--muted-foreground,#888)]">{label}：</span>
      {value && value !== "" ? <MathText text={value} /> : <span className="text-[var(--muted-foreground,#aaa)]">（未作答）</span>}
    </div>
  );
}

function HistoryRow({ item }: { item: HistoryItem }) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<HistoryDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [added, setAdded] = useState(false);
  const [addBusy, setAddBusy] = useState(false);

  const inWrongbook = !!item.wrong_question_id || added;

  const toggle = useCallback(async () => {
    const nextOpen = !open;
    setOpen(nextOpen);
    if (nextOpen && !detail && !loadingDetail) {
      setLoadingDetail(true);
      setDetailError(null);
      try {
        setDetail(await historyDetail(item.id));
      } catch (e) {
        setDetailError(e instanceof Error ? e.message : "详情加载失败");
      } finally {
        setLoadingDetail(false);
      }
    }
  }, [open, detail, loadingDetail, item.id]);

  const addWrong = useCallback(async () => {
    setAddBusy(true);
    try {
      await addToWrongbook(item.id);
      setAdded(true);
    } catch (e) {
      setDetailError(e instanceof Error ? e.message : "加入错题本失败");
    } finally {
      setAddBusy(false);
    }
  }, [item.id]);

  return (
    <OCard data-testid="history-item">
      <button
        type="button"
        className="w-full p-4 text-left"
        aria-expanded={open}
        onClick={() => void toggle()}
      >
        <div className="flex min-w-0 items-start gap-3">
          {item.has_image && <HistoryThumbnail recordId={item.id} />}
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-lg" aria-hidden>{resultIcon(item.is_correct)}</span>
                <span className="truncate text-sm text-[var(--muted-foreground,#888)]">{item.source_label}</span>
                {item.subject && (
                  <span className="shrink-0 rounded-full bg-[var(--muted,#f3f3f3)] px-2 py-0.5 text-xs">
                    {subjectLabel(item.subject)}
                  </span>
                )}
              </div>
              <span className="shrink-0 text-sm tabular-nums text-[var(--muted-foreground,#888)]">
                {beijingTime(item.created_at)}
              </span>
            </div>
            <div className="mt-2 line-clamp-2 break-words text-base">
              {item.question_text ? <MathText text={item.question_text} /> : "（含图题）"}
            </div>
          </div>
        </div>
      </button>

      {open && (
        <div className="space-y-3 border-t p-4">
          {loadingDetail && (
            <div className="text-sm text-[var(--muted-foreground,#888)]">加载详情…</div>
          )}
          {detailError && (
            <div className="text-base text-[var(--destructive,#c00)]">{detailError}</div>
          )}
          {detail && (
            <div className="space-y-2">
              <div className="rounded-xl bg-[var(--muted,#f6f6f6)] p-3 text-base">
                <MathText text={detail.question_text} />
              </div>
              {detail.has_image && <DetailImage recordId={detail.id} />}
              <DetailRow label="你的答案" value={detail.student_answer} />
              <DetailRow label="正确答案" value={detail.correct_answer} />
              <div className="text-sm text-[var(--muted-foreground,#888)]">
                判分方式：{graderLabel(detail.grader)}
              </div>
            </div>
          )}

          <OButton
            variant="outline"
            className="w-full min-h-[44px] text-base"
            loading={addBusy}
            disabled={addBusy || inWrongbook}
            onClick={() => void addWrong()}
          >
            {inWrongbook ? "已在错题本" : "加入错题本"}
          </OButton>
        </div>
      )}
    </OCard>
  );
}

export default function HistoryPage() {
  const [result, setResult] = useState<HistoryResult | null>(null);
  const [subject, setSubject] = useState("");
  const [source, setSource] = useState("");

  const [items, setItems] = useState<HistoryItem[]>([]);
  const [summaryDays, setSummaryDays] = useState<HistorySummaryDay[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);
  const reqRef = useRef(0);

  const load = useCallback(
    async (offset: number) => {
      const reqId = ++reqRef.current;
      if (offset === 0) setLoading(true);
      else setLoadingMore(true);
      setError(null);
      try {
        const page = await historyList({
          subject: subject || undefined,
          source: source || undefined,
          result: result ?? undefined,
          limit: PAGE_SIZE,
          offset,
        });
        // 迟到的旧请求不得覆盖新结果。
        if (reqId !== reqRef.current) return;
        setTotal(page.total);
        setItems((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      } catch (e) {
        if (reqId === reqRef.current) setError(e instanceof Error ? e.message : "加载失败");
      } finally {
        if (reqId === reqRef.current) {
          setLoading(false);
          setLoadingMore(false);
        }
      }
    },
    [subject, source, result]
  );

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    void historySummary(30).then((summary) => setSummaryDays(summary?.days ?? []));
  }, []);

  useEffect(() => {
    void load(0);
  }, [load, reloadKey]);

  return (
    <main className="mx-auto max-w-xl p-4 space-y-4" data-testid="history-root">
      <h1 className="text-2xl font-bold">做题记录</h1>
      <ProductNav />

      {/* 筛选条：横向滚动，不撑破页面 */}
      <div className="-mx-4 overflow-x-auto px-4">
        <div className="flex w-max gap-2">
          {RESULT_CHIPS.map((c) => {
            const active = result === c.value;
            return (
              <button
                key={c.label}
                type="button"
                aria-pressed={active}
                className={`min-h-[44px] rounded-full border px-4 text-base ${
                  active
                    ? "bg-[var(--primary)] text-[var(--primary-foreground)] border-transparent"
                    : "bg-[var(--background)] border-[var(--border)]"
                }`}
                onClick={() => setResult(c.value)}
              >
                {c.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3">
        <label className="space-y-1">
          <span className="text-sm text-[var(--muted-foreground,#888)]">科目</span>
          <select
            className="min-h-[44px] w-full rounded-xl border bg-[var(--background)] px-3 text-base"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
          >
            <option value="">全部科目</option>
            {SUBJECT_OPTIONS.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </label>
        <label className="space-y-1">
          <span className="text-sm text-[var(--muted-foreground,#888)]">来源</span>
          <select
            className="min-h-[44px] w-full rounded-xl border bg-[var(--background)] px-3 text-base"
            value={source}
            onChange={(e) => setSource(e.target.value)}
          >
            {SOURCES.map((s) => (
              <option key={s.value} value={s.value}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      {error && (
        <OCard>
          <div className="space-y-3 p-4 text-base text-[var(--destructive,#c00)]">
            <div>{error}</div>
            <OButton variant="outline" className="min-h-[44px]" onClick={() => setReloadKey((k) => k + 1)}>
              重试
            </OButton>
          </div>
        </OCard>
      )}

      {loading && (
        <div className="p-4 text-base text-[var(--muted-foreground,#888)]">加载中…</div>
      )}

      {!loading && !error && items.length === 0 && (
        <OCard>
          <div className="p-4">
            <OEmptyState
              title="还没有记录"
              description="拍一道题，或做几道练习，这里就会留下你的足迹。"
            />
          </div>
        </OCard>
      )}

      {!loading &&
        groupHistoryByDay(items).map(({ date, items: dayItems }) => {
          const summary = summaryDays.find((day) => day.date === date);
          const topWrong = summary?.top_wrong_kcs?.[0];
          return (
            <section key={date} className="space-y-2" data-testid="history-day">
              <header className="space-y-1">
                <h2 className="text-lg font-bold">{historyDayTitle(date)}</h2>
                <p className="text-sm text-[var(--muted-foreground,#777)]">
                  {summary ? (
                    <>
                      {summary.count} 题
                      {summary.correct != null || summary.wrong != null
                        ? ` · 对 ${summary.correct ?? 0} 错 ${summary.wrong ?? 0}`
                        : ""}
                      {typeof summary.accuracy === "number" ? ` · 正确率 ${Math.round(summary.accuracy * 100)}%` : ""}
                      {typeof summary.minutes === "number" ? ` · ${summary.minutes} 分钟` : ""}
                      {topWrong ? ` · 错得最多：${kpName(topWrong.name || topWrong.kc_id)}` : ""}
                    </>
                  ) : (
                    `${dayItems.length} 条记录 · 暂无当日汇总`
                  )}
                </p>
              </header>
              <div className="space-y-3">
                {dayItems.map((it) => <HistoryRow key={it.id} item={it} />)}
              </div>
            </section>
          );
        })}

      {!loading && items.length < total && (
        <OButton
          variant="outline"
          className="w-full min-h-[48px] text-base"
          loading={loadingMore}
          disabled={loadingMore}
          onClick={() => void load(items.length)}
        >
          加载更多
        </OButton>
      )}

      {!loading && items.length > 0 && items.length >= total && (
        <div className="text-center text-sm text-[var(--muted-foreground,#888)]">
          共 {total} 条
        </div>
      )}

      <div className="text-center text-sm">
        <Link href="/ask" className="text-[var(--primary)] underline underline-offset-4">
          去拍一道题
        </Link>
      </div>
    </main>
  );
}
