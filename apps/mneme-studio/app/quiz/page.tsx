"use client";

import { OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";

// Quiz 壳 —— 留 W2b 后续。
export default function QuizPage() {
  return (
    <main className="mx-auto max-w-2xl p-6" data-testid="quiz-root">
      <OCard>
        <OCardHeader><OCardTitle>小测</OCardTitle></OCardHeader>
        <div className="p-4">
          <OEmptyState title="小测工作区" description="W2b 后续开放。" />
        </div>
      </OCard>
    </main>
  );
}
