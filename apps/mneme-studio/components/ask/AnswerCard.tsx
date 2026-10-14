"use client";

// AnswerCard —— 有"卡片型答案"的题型（内核确定性产出），比 hint/steps 更好读：
//   单词卡（大词 + 音标 + 释义 + 变形/标签 chip）、古诗卡（居中 + 答案行高亮）、
//   拼音卡（ruby 注音）、成语卡（释义 + 出处 + 例句）。
// 没有 card（数学题等）→ 组件返回 null，页面退回 hint/steps/answer 老 UI。

import type { AnswerCard as Card } from "@/lib/questions";

function Chips({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-sm text-[var(--muted-foreground,#888)]">{label}</span>
      {items.map((t, i) => (
        <span
          key={`${t}-${i}`}
          className="rounded-full bg-[var(--secondary)] px-2.5 py-0.5 text-sm text-[var(--secondary-foreground)]"
        >
          {t}
        </span>
      ))}
    </div>
  );
}

function WordCard({ card }: { card: Extract<Card, { type: "english_word" }> }) {
  // inflections 值可能是 string | string[]，统一摊平成 chip。
  const inflections: string[] = Object.values(card.inflections ?? {}).flatMap((v) =>
    Array.isArray(v) ? v.map(String) : v == null ? [] : [String(v)]
  );
  return (
    <div className="space-y-3 rounded-xl border p-5 text-center" data-testid="answer-card-word">
      <div className="text-4xl font-bold tracking-tight break-words">{card.word}</div>
      {card.phonetic && (
        <div className="text-lg text-[var(--muted-foreground,#666)]">/{card.phonetic}/</div>
      )}
      <ol className="mx-auto max-w-sm space-y-1 text-left text-base">
        {card.meanings.map((m, i) => (
          <li key={i} className="flex gap-2">
            <span className="shrink-0 text-[var(--muted-foreground,#888)]">{i + 1}.</span>
            <span className="whitespace-pre-wrap">{m}</span>
          </li>
        ))}
      </ol>
      <Chips label="变形" items={inflections} />
      <Chips label="标签" items={card.tags ?? []} />
    </div>
  );
}

function PoemCard({ card }: { card: Extract<Card, { type: "poem" }> }) {
  return (
    <div className="space-y-3 rounded-xl border px-3 py-4" data-testid="answer-card-poem">
      <div className="text-center">
        <div className="text-2xl font-bold">{card.title}</div>
        <div className="mt-1 text-base text-[var(--muted-foreground,#666)]">
          〔{card.dynasty}〕{card.author}
        </div>
      </div>
      <div className="mx-auto max-w-sm space-y-1.5 text-center text-base leading-relaxed sm:text-lg">
        {card.lines.map((line, i) => {
          const isAnswer = card.highlight === i;
          const isBlank = card.answer != null && line.includes("○");
          return (
            <div
              key={i}
              className={`rounded-lg px-2 py-1 ${
                isAnswer ? "bg-[var(--secondary)] font-semibold" : ""
              } ${isBlank && !isAnswer ? "text-[var(--muted-foreground,#999)]" : ""}`}
            >
              {line.split(/(?<=[，,；;])/).map((seg, j) => (
                <span key={j} className="inline-block">{seg}</span>
              ))}
            </div>
          );
        })}
      </div>
      {card.answer && (
        <div className="mx-auto max-w-sm rounded-lg bg-[var(--secondary)] p-3 text-center text-lg">
          <span className="mr-2 text-sm text-[var(--muted-foreground,#666)]">答案</span>
          <span className="font-semibold">{card.answer}</span>
        </div>
      )}
    </div>
  );
}

function PinyinCard({ card }: { card: Extract<Card, { type: "pinyin" }> }) {
  return (
    <div className="rounded-xl border p-5" data-testid="answer-card-pinyin">
      <div className="flex flex-wrap justify-center gap-x-5 gap-y-3">
        {card.items.map((it, i) => (
          <ruby
            key={`${it.char}-${i}`}
            className="text-3xl leading-none"
          >
            {it.char}
            <rp>(</rp>
            <rt className="text-sm text-[var(--muted-foreground,#666)]">{it.pinyin}</rt>
            <rp>)</rp>
          </ruby>
        ))}
      </div>
    </div>
  );
}

function IdiomCard({ card }: { card: Extract<Card, { type: "idiom" }> }) {
  return (
    <div className="space-y-3 rounded-xl border p-5" data-testid="answer-card-idiom">
      <div className="text-center">
        <div className="text-3xl font-bold tracking-[0.2em]">{card.word}</div>
        {card.pinyin && (
          <div className="mt-1 text-base text-[var(--muted-foreground,#666)]">{card.pinyin}</div>
        )}
      </div>
      <div className="text-base leading-relaxed">
        <span className="mr-1.5 rounded bg-[var(--secondary)] px-1.5 py-0.5 text-sm">释义</span>
        {card.explanation}
      </div>
      {card.derivation && (
        <div className="text-base leading-relaxed text-[var(--muted-foreground,#555)]">
          <span className="mr-1.5 rounded bg-[var(--secondary)] px-1.5 py-0.5 text-sm">出处</span>
          {card.derivation}
        </div>
      )}
      {card.example && (
        <div className="rounded-lg bg-[var(--muted,#f6f6f6)] p-3 text-base leading-relaxed">
          <span className="mr-1.5 text-sm text-[var(--muted-foreground,#666)]">例句</span>
          {card.example}
        </div>
      )}
    </div>
  );
}

export function AnswerCard({ card }: { card: Card | null | undefined }) {
  if (!card) return null;
  switch (card.type) {
    case "english_word":
      return <WordCard card={card} />;
    case "poem":
      return <PoemCard card={card} />;
    case "pinyin":
      return <PinyinCard card={card} />;
    case "idiom":
      return <IdiomCard card={card} />;
    default:
      // 未知 card 类型：不猜、不崩，退回老 UI。
      return null;
  }
}

/** 内核名字（kernel）→ 给家长/学生看的一行小字。 */
export function kernelLabel(kernel: string | null | undefined): string | null {
  if (!kernel) return null;
  const k = kernel.toLowerCase();
  if (k.startsWith("english")) return "英语内核";
  if (k.startsWith("chinese")) return "语文内核";
  if (k.startsWith("chemistry")) return "化学内核";
  if (k.startsWith("math")) return "数学内核";
  return null;
}

/** solver → 角标文案。provider 是教学引擎讲解，与 llm（通用讲解）区分开。 */
export function solverLabel(solver: string | null | undefined): string | null {
  switch (solver) {
    case "kernel":
      return "精确求解";
    case "provider":
      return "教学引擎";
    case "llm":
      return "AI 讲解";
    default:
      return null;
  }
}
