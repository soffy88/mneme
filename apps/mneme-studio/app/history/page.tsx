"use client";

// /studio/history —— 做题记录（移动端优先）。
//
// 列表来自 /v1/questions/history（分页 + 筛选），详情来自 /v1/questions/history/{id}。
// 筛选条横向滚动，不撑破页面；详情在卡片内就地展开。

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { OButton, OCard, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { SUBJECT_OPTIONS, formatWhen, subjectLabel } from "@/lib/format";
import { MathText } from "@/components/MathText";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  addToWrongbook, fetchQuestionImageUrl, historyDetail, historyList,
  type HistoryDetail, type HistoryItem, type HistoryResult,
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
    <img src={url} alt="题目图片" className="mx-auto max-h-64 w-auto rounded-lg border object-contain" />
  );
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
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="text-lg" aria-hidden>{resultIcon(item.is_correct)}</span>
            <span className="truncate text-sm text-[var(--muted-foreground,#888)]">
              {item.source_label}
              {item.subject ? ` · ${subjectLabel(item.subject)}` : ""}
            </span>
          </div>
          <span className="shrink-0 text-sm text-[var(--muted-foreground,#888)]">
            {formatWhen(item.created_at)}
          </span>
        </div>
        <div className="mt-2 line-clamp-2 text-base">
          {item.question_text ? <MathText text={item.question_text} /> : "（含图题）"}
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
                判分方式：{detail.grader || "—"}
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
        items.map((it) => <HistoryRow key={it.id} item={it} />)}

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
