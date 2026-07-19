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

import { useEffect, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { mcp, getToken, redirectToLogin, type BookDetail, type BookSummary, type BookBlock } from "@/lib/mcp";
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
    return <OEmptyState title="还没有活书" description="Book Engine 还没编出任何一本书。" />;
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
