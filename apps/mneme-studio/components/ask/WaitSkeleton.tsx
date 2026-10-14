"use client";

// 识别/解题等待态：三行骨架 + 秒表。等待对小学生最难熬，"正在做什么 + 已经等了多久"
// 比一个转圈更能安抚——他知道系统还在干活，不是卡死了。

interface Props {
  /** 标题，如「正在识别题目…」/「正在解题…」。 */
  title: string;
  /** 已等待秒数（调用方用 setInterval 推进）。 */
  seconds: number;
  /** 超过这个秒数就加一句安抚的话。 */
  hintAfterSeconds?: number;
}

export function WaitSkeleton({ title, seconds, hintAfterSeconds = 8 }: Props) {
  const slow = seconds >= hintAfterSeconds;
  return (
    <div
      className="space-y-4 rounded-xl border p-5"
      role="status"
      aria-live="polite"
      data-testid="ask-waiting"
    >
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-lg font-semibold">{title}</span>
        <span className="text-base tabular-nums text-[var(--muted-foreground,#888)]">
          已等 {seconds} 秒
        </span>
      </div>

      <div className="space-y-2.5" aria-hidden>
        {[100, 92, 70].map((w, i) => (
          <div
            key={i}
            className="h-4 animate-pulse rounded bg-[var(--muted,#eee)]"
            style={{ width: `${w}%`, animationDelay: `${i * 120}ms` }}
          />
        ))}
      </div>

      {slow && (
        <div className="text-sm text-[var(--muted-foreground,#888)]">
          题目有点难，老师在慢慢想，稍等一下～
        </div>
      )}
    </div>
  );
}
