"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import {
  getStudentId, getToken, mcp, redirectToLogin,
  type MasteryPathView, type MasteryPathNode,
} from "@/lib/mcp";

// 掌握路径：按教材章节序排列的知识点，状态全部来自服务端内核（is_mastered），
// 前端不计算、不推断掌握度。当前知识点过门之前，后面的知识点保持锁定。

const STATE_STYLE: Record<MasteryPathNode["state"], { label: string; icon: string; bg: string }> = {
  mastered: { label: "已掌握", icon: "✓", bg: "var(--o-color-success-subtle,#e6f7e6)" },
  current: { label: "正在学", icon: "▶", bg: "var(--o-color-primary-subtle,#e8f0ff)" },
  locked: { label: "未解锁", icon: "🔒", bg: "var(--o-color-bg-subtle,#f2f2f2)" },
};

const ACTION_LABEL: Record<string, string> = {
  probe: "认识新知识点", practice: "继续练习", review: "先复习到期内容", assess: "讲讲你的理解",
  answer_pending: "有一道题等你作答", complete: "全部学完",
};

export default function PathPage() {
  const [view, setView] = useState<MasteryPathView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAllLocked, setShowAllLocked] = useState(false);

  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    void mcp.getMasteryPath(getStudentId()!).then(setView).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const nodes = view?.nodes ?? [];
  const firstLocked = nodes.findIndex((n) => n.state === "locked");
  const visible = showAllLocked || firstLocked < 0 ? nodes : nodes.slice(0, firstLocked + 3);
  const hidden = nodes.length - visible.length;
  const currentName = nodes.find((n) => n.kc_id === view?.current_kc_id)?.name ?? null;
  const pct = view && view.total_kps ? Math.round((view.total_mastered / view.total_kps) * 100) : 0;

  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4" data-testid="path-root">
      <h1 className="text-2xl font-bold">掌握路径</h1>
      <ProductNav />

      {error && <OCard><div className="p-4 text-sm text-[var(--o-color-danger,#c00)]">出错了：{error}</div></OCard>}
      {!view && !error && <OEmptyState title="正在读取路径…" description="" />}
      {view && view.status !== "completed" && (
        <OEmptyState title="路径暂不可用" description={view.status === "empty" ? "当前教材还没有可学的知识点。" : "读取掌握状态失败，请稍后刷新。"} />
      )}

      {view && view.status === "completed" && (
        <>
          <OCard data-testid="path-summary">
            <div className="p-4 space-y-3">
              <div className="flex items-baseline justify-between">
                <span className="text-lg font-semibold">已掌握 {view.total_mastered} / {view.total_kps}</span>
                {view.pending_review_count > 0 && (
                  <Link href="/practice" className="text-sm underline">{view.pending_review_count} 个知识点到期复习 →</Link>
                )}
              </div>
              <div className="h-2 w-full rounded-full bg-[var(--o-color-bg-subtle,#eee)]">
                <div className="h-2 rounded-full bg-[var(--o-color-success,#2a2)]" style={{ width: `${pct}%` }} />
              </div>
              {view.next && (
                <div className="flex items-center justify-between text-sm">
                  <span>下一步：{ACTION_LABEL[view.next.action] ?? view.next.action}{view.next.kc_name ? ` · ${view.next.kc_name}` : ""}</span>
                  {view.next.action !== "complete" && (
                    <Link href="/learn" className="rounded-md bg-[var(--o-color-primary,#2563eb)] px-3 py-1 text-white" data-testid="path-continue">继续学习</Link>
                  )}
                </div>
              )}
            </div>
          </OCard>

          <OCard data-testid="path-nodes">
            <OCardHeader><OCardTitle>按章节顺序</OCardTitle></OCardHeader>
            <ol className="p-4 space-y-2">
              {visible.map((n, i) => {
                const st = STATE_STYLE[n.state];
                return (
                  <li key={n.kc_id} className="flex items-center gap-3 rounded-lg p-3" style={{ background: st.bg, opacity: n.state === "locked" ? 0.7 : 1 }} data-state={n.state}>
                    <span className="w-6 text-center text-sm text-[var(--o-color-fg-muted,#888)]">{i + 1}</span>
                    <span aria-hidden className="w-5 text-center">{st.icon}</span>
                    <div className="flex-1 min-w-0">
                      <div className={`truncate ${n.state === "current" ? "font-semibold" : ""}`}>{n.name}</div>
                      <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
                        {st.label}{n.state === "locked" && currentName && !(n.review_due || n.n_obs > 0) ? ` · 先完成「${currentName}」` : ""}{n.kc_type === "concept" ? " · 概念理解" : ""}{n.n_obs > 0 ? ` · 作答 ${n.n_obs} 次` : ""}{n.review_due ? " · 到期复习" : ""}
                      </div>
                    </div>
                    {n.state === "current" && <Link href="/learn" className="text-sm underline">去学</Link>}
                    {n.state === "mastered" && n.review_due && <Link href="/practice" className="text-sm underline">复习</Link>}
                    {n.state === "locked" && (n.review_due || n.n_obs > 0) && <Link href="/practice" className="text-sm underline">练习</Link>}
                  </li>
                );
              })}
            </ol>
            {hidden > 0 && (
              <button className="w-full p-3 text-sm underline" onClick={() => setShowAllLocked(true)}>
                还有 {hidden} 个未解锁的知识点，展开全部
              </button>
            )}
          </OCard>
          <div className="text-xs text-[var(--o-color-fg-muted,#888)]">
            “已掌握”由 Mneme 的认知模型根据你的真实作答判定（证据不足不会提前解锁）；完成当前知识点后，下一个自动解锁（未解锁的知识点服务端不会出新题；复习和错题练习不受限制）。
          </div>
        </>
      )}
    </main>
  );
}
