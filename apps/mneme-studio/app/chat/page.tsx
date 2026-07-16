"use client";

import { OCard, OCardHeader, OCardTitle, OEmptyState } from "@helios/blocks";

// Chat 壳 —— intent_router 接入留 W2b 后续。
export default function ChatPage() {
  return (
    <main className="mx-auto max-w-2xl p-6" data-testid="chat-root">
      <OCard>
        <OCardHeader><OCardTitle>对话</OCardTitle></OCardHeader>
        <div className="p-4">
          <OEmptyState title="对话工作区" description="intent_router 接入后开放（W2b）。" />
        </div>
      </OCard>
    </main>
  );
}
