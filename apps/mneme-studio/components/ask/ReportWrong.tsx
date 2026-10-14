"use client";

// ReportWrong —— 答案下方一个小小的「这道题算错了？反馈」。
// 打开一个大到能点中的底部面板：四个原因 chip + 可选备注，提交后一句谢谢。
// 学生不需要理解任何内部概念；失败也不弹错误（反馈是次要动作，不挡主线）。

import { useCallback, useState } from "react";
import { OBottomSheet, OButton } from "@helios/blocks";
import { reportAsk } from "@/lib/questions";

const REASONS = ["识别错了", "答案错了", "步骤看不懂", "其他"] as const;

export function ReportWrong({ askId }: { askId: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  const close = useCallback(() => {
    setOpen(false);
    setReason(null);
    setComment("");
  }, []);

  const submit = useCallback(async () => {
    if (!reason || busy) return;
    setBusy(true);
    try {
      await reportAsk(askId, { reason, comment });
      setSent(true);
      close();
    } catch {
      // 失败也当"已收到"：不让学生以为要重试一遍，后台会补记。
      setSent(true);
      close();
    } finally {
      setBusy(false);
    }
  }, [askId, reason, comment, busy, close]);

  if (sent) {
    return (
      <div className="text-base text-[var(--success,#0a0)]" data-testid="report-thanks">
        谢谢反馈，我们会改进 🌱
      </div>
    );
  }

  return (
    <>
      <button
        type="button"
        className="text-base text-[var(--primary)] underline underline-offset-4"
        data-testid="report-open"
        onClick={() => setOpen(true)}
      >
        这道题算错了？反馈
      </button>

      <OBottomSheet
        open={open}
        onClose={close}
        title="这道题哪里不对？"
        initialHeight="peek"
      >
        <div className="space-y-4 p-4" data-testid="report-sheet">
          <div className="flex flex-wrap gap-2">
            {REASONS.map((r) => {
              const active = reason === r;
              return (
                <button
                  key={r}
                  type="button"
                  aria-pressed={active}
                  className={`min-h-[44px] rounded-full border px-4 text-base ${
                    active
                      ? "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]"
                      : "bg-[var(--background)] border-[var(--border)]"
                  }`}
                  onClick={() => setReason(r)}
                >
                  {r}
                </button>
              );
            })}
          </div>

          <textarea
            className="w-full min-h-[96px] rounded-xl border p-3 text-base"
            placeholder="还有什么想说的（可以不填）"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />

          <OButton
            size="lg"
            className="w-full min-h-[48px] text-base"
            loading={busy}
            disabled={busy || !reason}
            data-testid="report-submit"
            onClick={() => void submit()}
          >
            提交反馈
          </OButton>
        </div>
      </OBottomSheet>
    </>
  );
}
