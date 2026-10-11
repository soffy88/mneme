"use client";

// /studio/book —— 活书阅读器（W3 Part B B4）。
//
// FC-5：零 DB，唯一数据通道是 mcp.listBooks()/mcp.getBook()（同 lib/mcp.ts 里
// 其他工具一致的 HTTP /mcp/* 调用）。原有 /studio/learn 等页面零改动，本页是
// 新增独立路由。
//
// quiz/flash_cards/guided 三种块本身是"这块覆盖哪些 KC"的编译期占位（B2 设计：
// 具体题目/卡片/下一步是 per-student 实时数据，不在编译期固化），本页不在这里
// 重新实现选题/判分/FSRS 逻辑——只给一个指向既有 /studio/learn 的入口，避免
// 建第二条判分路径。

import { useCallback, useEffect, useRef, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import {
  mcp,
  getToken,
  redirectToLogin,
  McpError,
  listCompilableTextbooks,
  compileBook,
  bookCompileStatus,
  type BookDetail,
  type BookSummary,
  type BookBlock,
  type CompilableTextbook,
  type BookCompileStatus,
} from "@/lib/mcp";
import { MathText } from "@/components/MathText";
import { CitationNote } from "@/components/CitationNote";

function urlBookId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("book_id");
}

const CONTENT_TYPE_LABEL: Record<string, string> = {
  theory: "讲解", practice: "练习为主", concept: "概念",
};

function BlockView({ block }: { block: BookBlock }) {
  if (block.status !== "ready") {
    return (
      <div className="text-sm text-[var(--o-color-fg-muted,#888)]" data-testid="block-error">
        （这部分内容生成失败，暂时看不了）
      </div>
    );
  }

  const p = block.payload;

  if (block.block_type === "text" || block.block_type === "callout") {
    const text = String(p.text ?? "");
    return (
      <div className="space-y-2" data-testid={`block-${block.block_type}`}>
        <div className={block.block_type === "callout" ? "rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-3" : ""}>
          <MathText text={text} />
        </div>
        {block.citations.length > 0 && (
          <div className="space-y-1">
            {block.citations.map((c) => (
              <CitationNote key={c.chunk_id} citation={c} />
            ))}
          </div>
        )}
      </div>
    );
  }

  if (block.block_type === "figure") {
    const latex = String(p.latex ?? "");
    const caption = String(p.caption ?? "");
    return (
      <div className="space-y-2" data-testid="block-figure">
        {latex ? (
          <div className="rounded-lg border p-4 text-center">
            <MathText text={latex} />
          </div>
        ) : (
          <div className="text-sm text-[var(--o-color-fg-muted,#888)]">（这部分公式暂时生成不出来）</div>
        )}
        {caption && <p className="text-xs text-[var(--o-color-fg-muted,#666)]">{caption}</p>}
        {block.citations.length > 0 &&
          block.citations.map((c) => <CitationNote key={c.chunk_id} citation={c} />)}
      </div>
    );
  }

  // quiz / flash_cards / guided：编译期只有 kc_ids scope，具体题目/卡片/下一步
  // 是 per-student 实时数据，交给既有 /studio/learn（不在阅读器里重新实现）。
  // 交接必须带上这块实际覆盖的 kc_ids——不然点进去的是 /studio/learn 的默认
  // 路径，不是这块讲的知识点，"从书连到学习循环"这句话就是假的（B-8）。
  const label = { quiz: "配套练习题", flash_cards: "记忆卡", guided: "下一步学习指引" }[block.block_type];
  const kcIds = Array.isArray(p.kc_ids) ? (p.kc_ids as string[]) : [];
  const learnHref = kcIds.length > 0 ? `/studio/learn?kcs=${encodeURIComponent(kcIds.join(","))}` : "/studio/learn";
  return (
    <OCard data-testid={`block-${block.block_type}`}>
      <div className="p-3 flex items-center justify-between text-sm">
        <span>📚 本节配有{label}，请前往「学习」页练习</span>
        <a href={learnHref} data-testid={`${block.block_type}-learn-link`}>
          <OButton size="sm">去学习</OButton>
        </a>
      </div>
    </OCard>
  );
}

function BookList({ books }: { books: BookSummary[] }) {
  if (books.length === 0) {
    return <OEmptyState title="还没有活书" description="在上面选一本教材生成第一本活书。" />;
  }
  return (
    <div className="space-y-3" data-testid="book-list">
      {books.map((b) => (
        <a key={b.book_id} href={`/studio/book?book_id=${b.book_id}`}>
          <OCard>
            <div className="p-4">
              <div className="font-medium">{b.title}</div>
              <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                {b.book_name}（{b.subject}/{b.grade}）
              </div>
              {b.description && <p className="text-sm mt-1">{b.description}</p>}
            </div>
          </OCard>
        </a>
      ))}
    </div>
  );
}


// ── 生成活书：选教材 → POST /v1/books/compile → 轮询 /v1/books/{id}/status → 打开 ──
// 编译每本约几毛钱，后端有每人每日限额 + 全站预算；同一本教材正在编时后端直接复用
// 那个任务（deduplicated）。正在跟踪的任务记在 localStorage，刷新页面后继续轮询。
const JOB_KEY = "mneme_book_compile_job";
const SUBJECT_LABEL: Record<string, string> = {
  math: "数学", chinese: "语文", english: "英语", physics: "物理", chemistry: "化学",
  biology: "生物", history: "历史", geography: "地理", politics: "政治",
};
const STATUS_LABEL: Record<string, string> = {
  queued: "排队中", compiling: "正在生成（通常几分钟）", ready: "已生成", partial: "已生成（部分内容不完整）", error: "生成失败",
};

function errorText(e: unknown): string {
  if (e instanceof McpError) {
    try {
      const d = (JSON.parse(e.detail) as { detail?: unknown }).detail;
      if (typeof d === "string") return d;
      if (e.status === 429) return "今天的生成额度已用完，明天再来";
    } catch {
      /* 非 JSON */
    }
  }
  return e instanceof Error ? e.message : String(e);
}

function CompileBookPanel() {
  const [textbooks, setTextbooks] = useState<CompilableTextbook[] | null>(null);
  const [dailyLimit, setDailyLimit] = useState<number | null>(null);
  const [subject, setSubject] = useState<string>("");
  const [textbookId, setTextbookId] = useState<string>("");
  const [job, setJob] = useState<BookCompileStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async (bookId: string) => {
    try {
      const st = await bookCompileStatus(bookId);
      setJob(st);
      if (st.status === "queued" || st.status === "compiling") {
        timer.current = setTimeout(() => void poll(bookId), 5000);
      } else {
        localStorage.removeItem(JOB_KEY);
      }
    } catch (e) {
      setErr(errorText(e));
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const r = await listCompilableTextbooks();
        setTextbooks(r.textbooks);
        setDailyLimit(r.is_admin ? null : r.daily_limit);
      } catch (e) {
        setErr(errorText(e));
      }
    })();
    const saved = localStorage.getItem(JOB_KEY);
    if (saved) void poll(saved);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [poll]);

  const subjects = Array.from(new Set((textbooks ?? []).map((t) => t.subject)));
  const visible = (textbooks ?? []).filter((t) => !subject || t.subject === subject);

  async function submit() {
    if (!textbookId) return;
    setBusy(true);
    setErr(null);
    try {
      const j = await compileBook(textbookId);
      localStorage.setItem(JOB_KEY, j.book_id);
      if (timer.current) clearTimeout(timer.current);
      await poll(j.book_id);
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const running = job !== null && (job.status === "queued" || job.status === "compiling");
  const done = job !== null && (job.status === "ready" || job.status === "partial");

  return (
    <OCard data-testid="compile-panel">
      <OCardHeader>
        <OCardTitle>生成活书</OCardTitle>
      </OCardHeader>
      <div className="p-4 space-y-3 text-sm">
        <p className="text-[var(--o-color-fg-muted,#666)]">
          选一本教材，系统会按它的知识结构编出一本带讲解、例图和配套练习的活书。
          {dailyLimit !== null && `每人每天最多 ${dailyLimit} 本。`}
        </p>
        {textbooks === null ? (
          <div className="text-[var(--o-color-fg-muted,#888)]">正在加载教材…</div>
        ) : textbooks.length === 0 ? (
          <div className="text-[var(--o-color-fg-muted,#888)]">暂时没有可以生成活书的教材。</div>
        ) : (
          <>
            <div className="flex gap-2">
              <select
                aria-label="学科"
                data-testid="compile-subject"
                className="rounded-lg border p-2"
                value={subject}
                onChange={(e) => {
                  setSubject(e.target.value);
                  setTextbookId("");
                }}
              >
                <option value="">全部学科</option>
                {subjects.map((s) => (
                  <option key={s} value={s}>{SUBJECT_LABEL[s] ?? s}</option>
                ))}
              </select>
              <select
                aria-label="教材"
                data-testid="compile-textbook"
                className="flex-1 rounded-lg border p-2"
                value={textbookId}
                onChange={(e) => setTextbookId(e.target.value)}
              >
                <option value="">选择教材…</option>
                {visible.map((t) => (
                  <option key={t.textbook_id} value={t.textbook_id}>
                    {t.book_name}（{t.grade}，{t.n_clusters} 章节{t.n_books > 0 ? `，已有 ${t.n_books} 本活书` : ""}）
                  </option>
                ))}
              </select>
            </div>
            <OButton data-testid="compile-submit" disabled={!textbookId || busy || running} onClick={() => void submit()}>
              {busy ? "提交中…" : running ? "生成中…" : "生成活书"}
            </OButton>
          </>
        )}
        {job && (
          <div data-testid="compile-status" className="rounded-lg bg-[var(--o-color-bg-subtle,#f6f6f6)] p-3 space-y-1">
            <div>
              <span className="font-medium">{job.book_name ?? job.title}</span>：{STATUS_LABEL[job.status] ?? job.status}
              {job.stale && "（长时间没有进展，可能需要重新提交）"}
            </div>
            {done && (
              <div className="flex items-center gap-2">
                <span>{job.n_chapters} 章 · {job.n_blocks} 个内容块</span>
                <a href={`/studio/book?book_id=${job.book_id}`} data-testid="compile-open">
                  <OButton size="sm">打开这本书</OButton>
                </a>
              </div>
            )}
            {job.status === "error" && job.error && (
              <div className="text-[var(--o-color-danger,#c00)]">{job.error}</div>
            )}
          </div>
        )}
        {err && <div className="text-[var(--o-color-danger,#c00)]" data-testid="compile-error">{err}</div>}
      </div>
    </OCard>
  );
}

export default function BookPage() {
  const [books, setBooks] = useState<BookSummary[] | null>(null);
  const [book, setBook] = useState<BookDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    void (async () => {
      try {
        const bookId = urlBookId();
        if (bookId) {
          const r = await mcp.getBook(bookId);
          setBook(r.book);
        } else {
          const r = await mcp.listBooks();
          setBooks(r.books);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  if (error) {
    return (
      <main className="mx-auto max-w-2xl p-6" data-testid="book-root">
        <OCard><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>
      </main>
    );
  }

  if (urlBookId() && !book) {
    return (
      <main className="mx-auto max-w-2xl p-6" data-testid="book-root">
        <OEmptyState title="正在打开这本书…" description="" />
      </main>
    );
  }

  if (!urlBookId()) {
    return (
      <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="book-root">
        <h1 className="text-2xl font-bold">善学记 · 活书</h1>
        <CompileBookPanel />
        {books === null ? <OEmptyState title="正在加载书单…" description="" /> : <BookList books={books} />}
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-6" data-testid="book-root">
      <header>
        <a href="/studio/book" className="text-sm text-[var(--o-color-fg-muted,#888)]">← 所有的书</a>
        <h1 className="text-2xl font-bold mt-1">{book!.title}</h1>
        {book!.description && <p className="text-sm text-[var(--o-color-fg-muted,#666)] mt-1">{book!.description}</p>}
      </header>

      {book!.chapters.map((ch) => (
        <OCard key={ch.chapter_id} data-testid="chapter">
          <OCardHeader>
            <OCardTitle>
              {ch.title}
              <span className="ml-2 text-xs font-normal text-[var(--o-color-fg-muted,#888)]">
                {CONTENT_TYPE_LABEL[ch.content_type] ?? ch.content_type}
              </span>
            </OCardTitle>
          </OCardHeader>
          <div className="p-4 space-y-4">
            {ch.blocks.map((block) => (
              <BlockView key={block.block_id} block={block} />
            ))}
          </div>
        </OCard>
      ))}
    </main>
  );
}
