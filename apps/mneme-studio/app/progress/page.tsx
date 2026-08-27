"use client";

import { useEffect, useState } from "react";
import { OCard, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { getStudentId, getToken, mcp, redirectToLogin, type ProductProgress } from "@/lib/mcp";

export default function ProgressPage() {
  const [progress, setProgress] = useState<ProductProgress | null>(null);
  useEffect(() => {
    if (!getToken() || !getStudentId()) { redirectToLogin(); return; }
    void mcp.productProgress(getStudentId()!).then(setProgress).catch(() => setProgress(null));
  }, []);
  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4">
      <h1 className="text-2xl font-bold">Progress</h1>
      <ProductNav />
      {!progress ? <OEmptyState title="No data yet" description="Activity progress 与 learning progress 会分开显示。" /> : (
        <>
          <OCard><div className="p-4 space-y-2"><h2 className="font-semibold">Activity Progress</h2><div>Active minutes: {progress.activity_progress.active_minutes ?? "Unknown"}</div><div>Attempts: {progress.activity_progress.attempts ?? "Unknown"}</div><div>Reviews: {progress.activity_progress.reviews ?? "Unknown"}</div><div>Learning days: {progress.activity_progress.learning_days ?? "Unknown"}</div></div></OCard>
          <OCard><div className="p-4 space-y-2"><h2 className="font-semibold">Learning Progress</h2><div>{progress.learning_progress.long_term_retention_label}</div><div>Retention and transfer use eligible evidence only.</div></div></OCard>
        </>
      )}
    </main>
  );
}
