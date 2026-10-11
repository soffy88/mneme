"use client";

// 「存到笔记本」按钮：聊天回答 / 活书内容块 / 写作草稿 / 解题结果共用。
// 点开后选一个自己的笔记本（默认「我的笔记」，没有就自动建），保存后显示 ✓。
// 只写学习者自己的笔记本；笔记不进掌握度/门控。

import { useState } from "react";
import { OButton } from "@helios/blocks";
import { getToken, redirectToLogin } from "@/lib/mcp";
import {
  notebooks,
  errorMessage,
  type NewRecord,
  type NotebookSummary,
} from "@/lib/notebook";

const LAST_KEY = "mneme_last_notebook";
const DEFAULT_NAME = "我的笔记";

export function SaveToNotebook({
  record,
  label = "存到笔记本",
  size = "sm",
}: {
  record: NewRecord;
  label?: string;
  size?: "sm" | "md";
}) {
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<NotebookSummary[] | null>(null);
  const [target, setTarget] = useState<string>("");
  const [state, setState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [msg, setMsg] = useState<string>("");

  async function openPicker() {
    if (!getToken()) {
      redirectToLogin();
      return;
    }
    setOpen(true);
    setState("idle");
    try {
      const r = await notebooks.list();
      setList(r.notebooks);
      const last = typeof window !== "undefined" ? localStorage.getItem(LAST_KEY) : null;
      const found = r.notebooks.find((n) => n.id === last);
      setTarget(found ? found.id : r.notebooks[0]?.id ?? "");
    } catch (e) {
      setList([]);
      setMsg(errorMessage(e));
    }
  }

  async function save() {
    setState("saving");
    try {
      const out = await notebooks.save({
        ...record,
        notebook_id: target || null,
        notebook_name: target ? null : DEFAULT_NAME,
      });
      if (typeof window !== "undefined") localStorage.setItem(LAST_KEY, out.notebook_id);
      setState("saved");
      setOpen(false);
    } catch (e) {
      setState("error");
      setMsg(errorMessage(e));
    }
  }

  if (state === "saved" && !open) {
    return (
      <span className="text-xs text-[var(--o-color-success,#2a7)]" data-testid="notebook-saved">
        ✓ 已存入笔记本 · <a href="/studio/notebook" className="underline">查看</a>
      </span>
    );
  }

  if (!open) {
    return (
      <OButton size={size} variant="outline" onClick={openPicker} data-testid="save-to-notebook">
        📒 {label}
      </OButton>
    );
  }

  return (
    <span className="inline-flex flex-wrap items-center gap-2 text-xs" data-testid="notebook-picker">
      <select
        className="rounded border px-2 py-1 text-xs bg-transparent"
        value={target}
        onChange={(e) => setTarget(e.target.value)}
        aria-label="选择笔记本"
      >
        {(list ?? []).map((n) => (
          <option key={n.id} value={n.id}>
            {n.name}
          </option>
        ))}
        {!(list ?? []).some((n) => n.name === DEFAULT_NAME) && <option value="">{`新建「${DEFAULT_NAME}」`}</option>}
      </select>
      <OButton size="sm" onClick={save} disabled={state === "saving" || list === null}>
        {state === "saving" ? "保存中…" : "保存"}
      </OButton>
      <button type="button" className="underline" onClick={() => setOpen(false)}>
        取消
      </button>
      {state === "error" && <span className="text-[var(--o-color-danger,#c00)]">{msg}</span>}
    </span>
  );
}
