"use client";

// /studio/notebook —— 我的笔记本（DeepTutor Notebook 对标）。
//
// 学习者把聊天回答、活书内容块、解题结果、写作草稿或随手记存进自己命名的笔记本。
// 数据通道 /v1/notebooks（owner-only：只有学生本人能看能改）。笔记只是自己的整理，
// 不进掌握度/门控。

import { useCallback, useEffect, useState } from "react";
import { OButton, OCard, OCardHeader, OCardTitle, OEmptyState, OInput, OBadge } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  notebooks,
  errorMessage,
  SOURCE_LABEL,
  type NotebookDetail,
  type NotebookSummary,
} from "@/lib/notebook";

function fmt(ts: string | null): string {
  if (!ts) return "";
  return new Date(ts).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function urlNotebookId(): string | null {
  if (typeof window === "undefined") return null;
  return new URLSearchParams(window.location.search).get("id");
}

export default function NotebookPage() {
  const [list, setList] = useState<NotebookSummary[] | null>(null);
  const [current, setCurrent] = useState<NotebookDetail | null>(null);
  const [newName, setNewName] = useState("");
  const [noteTitle, setNoteTitle] = useState("");
  const [noteText, setNoteText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const open = useCallback(async (id: string) => {
    setError(null);
    try {
      setCurrent(await notebooks.get(id));
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const r = await notebooks.list();
      setList(r.notebooks);
      return r.notebooks;
    } catch (e) {
      setError(errorMessage(e));
      setList([]);
      return [];
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    void (async () => {
      const nbs = await refresh();
      const want = urlNotebookId() ?? nbs[0]?.id;
      if (want) await open(want);
    })();
  }, [refresh, open]);

  async function createNotebook() {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    setError(null);
    try {
      const nb = await notebooks.create(name);
      setNewName("");
      await refresh();
      await open(nb.id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function addNote() {
    if (!current || !noteText.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await notebooks.addRecord(current.id, {
        source_type: "free_text",
        title: noteTitle.trim() || null,
        content: noteText.trim(),
      });
      setNoteText("");
      setNoteTitle("");
      await open(current.id);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  async function removeRecord(rid: string) {
    if (!current || !window.confirm("删除这条笔记？")) return;
    try {
      await notebooks.removeRecord(current.id, rid);
      await open(current.id);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function renameNotebook() {
    if (!current) return;
    const name = window.prompt("新的笔记本名字", current.name)?.trim();
    if (!name || name === current.name) return;
    try {
      await notebooks.rename(current.id, name);
      await open(current.id);
      await refresh();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function removeNotebook() {
    if (!current || !window.confirm(`删除笔记本「${current.name}」和里面的 ${current.record_count ?? 0} 条笔记？`)) return;
    try {
      await notebooks.remove(current.id);
      setCurrent(null);
      const nbs = await refresh();
      if (nbs[0]) await open(nbs[0].id);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <main className="mx-auto max-w-4xl p-6 space-y-4" data-testid="notebook-root">
      <ProductNav />
      <h1 className="text-2xl font-bold">我的笔记本</h1>
      <p className="text-sm text-[var(--o-color-fg-muted,#666)]">
        在对话、活书、写作助手里点「存到笔记本」，内容会出现在这里。笔记只有你自己能看到。
      </p>

      {error && (
        <div className="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
          {error}
        </div>
      )}

      <div className="grid gap-4 md:grid-cols-[220px_1fr]">
        <aside className="space-y-3">
          <OCard>
            <div className="p-3 space-y-2">
              {list === null && <div className="text-sm">加载中…</div>}
              {list?.length === 0 && <div className="text-sm text-[var(--o-color-fg-muted,#888)]">还没有笔记本</div>}
              {list?.map((nb) => (
                <button
                  key={nb.id}
                  type="button"
                  onClick={() => open(nb.id)}
                  className={`block w-full rounded px-2 py-1 text-left text-sm ${
                    current?.id === nb.id ? "bg-[var(--o-color-bg-subtle,#eef)] font-semibold" : ""
                  }`}
                  data-testid="notebook-item"
                >
                  {nb.name}
                  <span className="ml-1 text-xs text-[var(--o-color-fg-muted,#888)]">{nb.record_count ?? 0}</span>
                </button>
              ))}
            </div>
          </OCard>
          <div className="flex gap-2">
            <OInput
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="新笔记本名字"
              maxLength={100}
              onKeyDown={(e) => {
                if (e.key === "Enter") void createNotebook();
              }}
            />
            <OButton size="sm" onClick={createNotebook} disabled={busy || !newName.trim()}>
              新建
            </OButton>
          </div>
        </aside>

        <section className="space-y-4">
          {!current ? (
            <OEmptyState title="选一个笔记本，或者新建一个" description="" />
          ) : (
            <>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-xl font-semibold">{current.name}</h2>
                <div className="flex gap-2 text-sm">
                  <button type="button" className="underline" onClick={renameNotebook}>
                    改名
                  </button>
                  <button type="button" className="underline text-red-600" onClick={removeNotebook}>
                    删除笔记本
                  </button>
                </div>
              </div>

              <OCard>
                <div className="p-3 space-y-2">
                  <OInput
                    value={noteTitle}
                    onChange={(e) => setNoteTitle(e.target.value)}
                    placeholder="标题（可选）"
                    maxLength={200}
                  />
                  <textarea
                    value={noteText}
                    onChange={(e) => setNoteText(e.target.value)}
                    placeholder="随手记一点什么…"
                    rows={3}
                    maxLength={20000}
                    className="w-full rounded border p-2 text-sm bg-transparent"
                    data-testid="free-text-input"
                  />
                  <OButton size="sm" onClick={addNote} disabled={busy || !noteText.trim()}>
                    记下来
                  </OButton>
                </div>
              </OCard>

              {current.records.length === 0 ? (
                <OEmptyState title="这个笔记本还是空的" description="" />
              ) : (
                current.records.map((r) => (
                  <OCard key={r.id} data-testid="notebook-record">
                    <OCardHeader>
                      <OCardTitle>
                        <span className="mr-2">{r.title || SOURCE_LABEL[r.source_type] || r.source_type}</span>
                        <OBadge variant="outline" className="text-xs">
                          {SOURCE_LABEL[r.source_type] ?? r.source_type}
                        </OBadge>
                        {r.kc_id && (
                          <span className="ml-2 text-xs font-normal text-[var(--o-color-fg-muted,#888)]">
                            知识点 {r.kc_id}
                          </span>
                        )}
                      </OCardTitle>
                    </OCardHeader>
                    <div className="px-4 pb-4 space-y-2">
                      <div className="whitespace-pre-wrap text-sm">{r.content}</div>
                      <div className="flex items-center justify-between text-xs text-[var(--o-color-fg-muted,#888)]">
                        <span>{fmt(r.created_at)}</span>
                        <span className="flex gap-3">
                          {r.source_type === "book_block" && typeof r.metadata?.book_id === "string" && (
                            <a className="underline" href={`/studio/book?book_id=${encodeURIComponent(String(r.metadata.book_id))}`}>
                              回到书里
                            </a>
                          )}
                          {r.source_type === "cowriter" && (
                            <a className="underline" href={`/studio/cowriter?from=${encodeURIComponent(r.id)}&nb=${encodeURIComponent(r.notebook_id)}`}>
                              继续修改
                            </a>
                          )}
                          <button type="button" className="underline text-red-600" onClick={() => removeRecord(r.id)}>
                            删除
                          </button>
                        </span>
                      </div>
                    </div>
                  </OCard>
                ))
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}
