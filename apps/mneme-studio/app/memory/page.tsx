"use client";

import { useEffect, useState } from "react";
import { OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { getStudentId, getToken, mcp, redirectToLogin } from "@/lib/mcp";

type MemoryItem = { label: string; knowledge_ref?: string | null; evidence_refs: string[]; why_this: string[] };

export default function MemoryPage() {
  const [items, setItems] = useState<MemoryItem[]>([]);
  const [status, setStatus] = useState("加载中…");
  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    void mcp.productMemory(getStudentId()!).then((result) => {
      setItems(result.items as MemoryItem[]);
      setStatus(result.status);
    }).catch(() => setStatus("NO DATA"));
  }, []);
  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4">
      <h1 className="text-2xl font-bold">Memory</h1>
      <ProductNav />
      {items.length === 0 ? <OEmptyState title="No data yet" description="完成真实学习后，Mneme 会在这里显示 evidence-backed memory。" /> : items.map((item) => (
        <OCard key={item.knowledge_ref ?? item.label}>
          <OCardHeader><OCardTitle>{item.knowledge_ref ?? "Knowledge"}</OCardTitle></OCardHeader>
          <div className="p-4 space-y-2">
            <div className="text-lg font-semibold">{item.label}</div>
            <details><summary className="cursor-pointer">Why does Mneme think this?</summary><div className="pt-2 text-sm">{item.why_this.join(" · ")}</div></details>
          </div>
        </OCard>
      ))}
      {items.length > 0 && <div className="text-xs text-gray-500">{status} · 需要更多证据时会显示 Unknown，而不是虚假精度。</div>}
    </main>
  );
}
