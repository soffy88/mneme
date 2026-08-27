"use client";

import { useEffect, useState } from "react";
import { OCard, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { getStudentId, getToken, mcp, redirectToLogin } from "@/lib/mcp";

type WeakItem = { knowledge_ref: string; label: string; observed_pattern?: string | null; confidence?: number | null; supporting_evidence: string[]; recommended_repair_action?: string | null };

export default function WeakAreasPage() {
  const [items, setItems] = useState<WeakItem[]>([]);
  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    void mcp.productWeakAreas(getStudentId()!).then((result) => setItems(result.items as WeakItem[])).catch(() => setItems([]));
  }, []);
  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4">
      <h1 className="text-2xl font-bold">Weak Areas</h1>
      <ProductNav />
      {items.length === 0 ? <OEmptyState title="No evidence-backed misconception yet" description="证据不足时不会把可能性说成结论。" /> : items.map((item) => (
        <OCard key={`${item.knowledge_ref}-${item.label}`}>
          <div className="p-4 space-y-2">
            <div className="font-semibold">{item.label} · {item.knowledge_ref}</div>
            {item.observed_pattern && <div className="text-sm">Observed pattern: {item.observed_pattern}</div>}
            <div className="text-sm">Repair: {item.recommended_repair_action ?? "diagnostic repair"}</div>
            <div className="text-xs text-gray-500">Evidence: {item.supporting_evidence.join(", ")}</div>
          </div>
        </OCard>
      ))}
    </main>
  );
}
