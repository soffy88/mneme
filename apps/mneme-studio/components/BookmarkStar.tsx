"use client";

import { useEffect, useState } from "react";
import { mcp, type BookmarkSource } from "@/lib/mcp";

// ☆ 收藏按钮：服务端按 (student, question_id) 取题干快照，前端只传来源 + id，
// 不接触答案。收藏不影响掌握度 / 复习排程。
export function BookmarkStar(props: {
  studentId: string;
  source: BookmarkSource;
  questionId: string;
  bookmarkId?: string | null;
  onChange?: (bookmarkId: string | null) => void;
}) {
  const { studentId, source, questionId, onChange } = props;
  const [bid, setBid] = useState<string | null>(props.bookmarkId ?? null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(false);

  useEffect(() => { setBid(props.bookmarkId ?? null); }, [props.bookmarkId, questionId]);

  const toggle = async () => {
    if (busy || !studentId) return;
    setBusy(true); setErr(false);
    try {
      if (bid) {
        await mcp.removeBookmark(bid);
        setBid(null); onChange?.(null);
      } else {
        const b = await mcp.addBookmark(studentId, source, questionId);
        setBid(b.id); onChange?.(b.id);
      }
    } catch {
      setErr(true);
    } finally {
      setBusy(false);
    }
  };

  const on = !!bid;
  return (
    <button
      type="button"
      onClick={() => void toggle()}
      disabled={busy}
      aria-pressed={on}
      aria-label={on ? "取消收藏" : "收藏这道题"}
      title={err ? "收藏失败，请重试" : on ? "取消收藏" : "收藏这道题"}
      className="rounded-md px-2 py-1 text-sm hover:bg-[var(--o-color-bg-subtle,#f2f2f2)]"
      style={{ color: on ? "var(--o-color-warning,#d4a000)" : "var(--o-color-fg-muted,#888)" }}
      data-testid="bookmark-star"
      data-bookmarked={on ? "1" : "0"}
    >
      {on ? "★ 已收藏" : "☆ 收藏"}{err ? " !" : ""}
    </button>
  );
}
