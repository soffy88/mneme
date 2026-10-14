"use client";

// MathKeyboard —— 学生在手机上改识别结果时，最恨的就是找不到 ÷、√、x²。
// 这就是一排"插入到光标处"的符号按钮（不改文本其余部分，也不抢焦点）。

import { useCallback } from "react";

const KEYS = ["x²", "√", "÷", "×", "≤", "≥", "≠", "π", "°", "(", ")"];

/** 分数：插入 "()/()" 并把光标放在第一个 () 里。 */
const FRACTION = { before: "()/()", cursorOffset: 1 };

interface Props {
  /** 目标 textarea 的 ref。 */
  target: React.RefObject<HTMLTextAreaElement | null>;
  /** 插入后用受控 value 同步回 React state（否则界面不更新）。 */
  onChange: (value: string) => void;
}

export function MathKeyboard({ target, onChange }: Props) {
  const insert = useCallback(
    (text: string, cursorBack = 0) => {
      const el = target.current;
      if (!el) return;
      const start = el.selectionStart ?? el.value.length;
      const end = el.selectionEnd ?? start;
      const next = el.value.slice(0, start) + text + el.value.slice(end);
      onChange(next);
      // selectionStart 要在 React 重渲染之后才设得上；用 rAF 等一帧。
      const caret = start + text.length - cursorBack;
      requestAnimationFrame(() => {
        el.focus();
        el.setSelectionRange(caret, caret);
      });
    },
    [target, onChange]
  );

  return (
    <div className="flex flex-wrap gap-1.5" data-testid="ask-math-keyboard">
      {KEYS.map((k) => (
        <button
          key={k}
          type="button"
          className="min-h-[40px] min-w-[40px] rounded-lg border bg-[var(--background)] px-2 text-base tabular-nums"
          onClick={() => insert(k)}
        >
          {k}
        </button>
      ))}
      <button
        type="button"
        className="min-h-[40px] rounded-lg border bg-[var(--background)] px-3 text-base"
        onClick={() => insert(FRACTION.before, FRACTION.before.length - FRACTION.cursorOffset)}
      >
        分数
      </button>
    </div>
  );
}
