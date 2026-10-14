"use client";

// LineTapper —— OCR 认出来好几行，但题目只占其中两行（上面是班级姓名、右边是页眉）。
// 让学生点图上的行 / 点下面的 chip 来勾选，按点击顺序拼成题干，再确认回到文本框改。
// 没有 lines（老服务端/纯文字输入）→ 组件不渲染，退回纯文本框。

import { useCallback, useMemo, useState } from "react";
import { OButton } from "@helios/blocks";
import type { AskLine } from "@/lib/questions";

interface Props {
  /** 裁剪后的图片 object URL（与 lines 的坐标系一致）。 */
  imageUrl: string;
  lines: AskLine[];
  /** 勾选变化 → 新文本（实时同步给页面的题干 state）。 */
  onChange: (text: string) => void;
  /** 确认这几行 → 收起选择器，进确认/解题步。 */
  onDone: () => void;
}

export function LineTapper({ imageUrl, lines, onChange, onDone }: Props) {
  const [picked, setPicked] = useState<number[]>([]);

  const toggle = useCallback(
    (i: number) => {
      setPicked((prev) => {
        const next = prev.includes(i) ? prev.filter((n) => n !== i) : [...prev, i];
        onChange(next.map((n) => lines[n].text).join(" "));
        return next;
      });
    },
    [lines, onChange]
  );

  const text = useMemo(() => picked.map((n) => lines[n].text).join(" "), [picked, lines]);

  return (
    <div className="space-y-3" data-testid="ask-lines">
      <div className="text-sm text-[var(--muted-foreground,#888)]">
        点一下题目所在的行（可点多行），点错的再点一次取消。
      </div>

      <div className="relative overflow-hidden rounded-xl border bg-black/5">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={imageUrl} alt="识别出的题目" className="block max-h-[55vh] w-full object-contain" />
        {lines.map((line, i) => {
          const [x0, y0, x1, y1] = line.box;
          const active = picked.includes(i);
          const order = active ? picked.indexOf(i) + 1 : null;
          return (
            <button
              key={i}
              type="button"
              aria-pressed={active}
              className={`absolute flex items-center justify-center rounded border-2 text-left text-[11px] leading-tight ${
                active
                  ? "border-[var(--primary)] bg-[var(--primary)]/25 font-semibold"
                  : "border-white/40 bg-white/10 hover:bg-white/25"
              }`}
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${Math.max(2.5, (y1 - y0) * 100)}%`,
                padding: 0,
              }}
              onClick={() => toggle(i)}
            >
              {order != null && (
                <span className="ml-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-[var(--primary)] text-[10px] text-[var(--primary-foreground)]">
                  {order}
                </span>
              )}
              <span className="line-clamp-2 px-0.5">{line.text}</span>
            </button>
          );
        })}
      </div>

      {/* 小屏兜底：图上的行太小点不准，芯片列表来一份 */}
      <div className="flex flex-wrap gap-1.5" data-testid="ask-line-chips">
        {lines.map((line, i) => {
          const active = picked.includes(i);
          return (
            <button
              key={i}
              type="button"
              aria-pressed={active}
              className={`max-w-full rounded-full border px-3 py-1.5 text-left text-sm ${
                active
                  ? "border-transparent bg-[var(--primary)] text-[var(--primary-foreground)]"
                  : "bg-[var(--background)] border-[var(--border)]"
              }`}
              onClick={() => toggle(i)}
            >
              {line.text}
            </button>
          );
        })}
      </div>

      <OButton
        size="lg"
        className="w-full min-h-[48px] text-base"
        data-testid="ask-lines-done"
        disabled={!text.trim()}
        onClick={() => {
          onChange(text);
          onDone();
        }}
      >
        {text.trim() ? `就这几行（${text.length} 字）` : "先选几行"}
      </OButton>
    </div>
  );
}
