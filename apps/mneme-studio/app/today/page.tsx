"use client";

import { useEffect, useState } from "react";
import { OCard, OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { getStudentId, getToken, redirectToLogin } from "@/lib/mcp";

export default function TodayPage() {
  const [message] = useState("Today tasks are selected by Mneme's Policy Engine.");
  useEffect(() => { if (!getToken() || !getStudentId()) redirectToLogin(); }, []);
  return (
    <main className="mx-auto max-w-2xl p-6 space-y-4">
      <h1 className="text-2xl font-bold">Today</h1>
      <ProductNav />
      <OCard><div className="p-4"><div>{message}</div><OEmptyState title="Open Learn Now" description="任务排序来自服务端 PolicyDecision；没有任务时显示 You’re caught up。" /></div></OCard>
    </main>
  );
}
