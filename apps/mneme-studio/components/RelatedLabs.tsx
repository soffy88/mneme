"use client";

// 相关实验：外链到 WeduLab（wedulab.com）的公开在线实验。
// 只做外链（源码未开源、无许可证）：新窗口打开、noopener/noreferrer、注明来源，不嵌入。

import { useEffect, useState } from "react";
import { fetchRelatedLabs, matchRelatedLabs, type RelatedLab } from "@/lib/mcp";

const SUBJECT_ORDER = ["math", "physics", "chemistry", "biology", "geography", "history"];

function LabLink({ lab }: { lab: RelatedLab }) {
  return (
    <a
      href={lab.url}
      target="_blank"
      rel="noopener noreferrer"
      data-testid={`related-lab-${lab.slug}`}
      className="block rounded-lg border px-3 py-2 text-sm hover:bg-black/5"
    >
      <div className="font-medium">{lab.title} ↗</div>
      <div className="text-xs text-[var(--o-color-fg-muted,#666)]">
        {lab.subject_label} · {lab.stages.join("、")} · {lab.topics.join("、")}
      </div>
    </a>
  );
}

function SourceNote() {
  return (
    <p className="text-xs text-[var(--o-color-fg-muted,#666)]">
      来自{" "}
      <a href="https://wedulab.com/" target="_blank" rel="noopener noreferrer" className="underline">
        WeduLab
      </a>
      （外部站点，新窗口打开）
    </p>
  );
}

/** 某个知识点的相关实验（无可靠命中时不渲染）。 */
export function RelatedLabsFor({ q, kcId, subject, limit = 2 }: { q?: string; kcId?: string; subject?: string; limit?: number }) {
  const [labs, setLabs] = useState<RelatedLab[]>([]);
  useEffect(() => {
    let alive = true;
    void matchRelatedLabs({ q, kcId, subject, limit })
      .then((r) => alive && setLabs(r))
      .catch(() => alive && setLabs([]));
    return () => {
      alive = false;
    };
  }, [q, kcId, subject, limit]);
  if (labs.length === 0) return null;
  return (
    <div className="space-y-1" data-testid="related-labs-for">
      <div className="text-xs font-semibold">相关实验</div>
      {labs.map((lab) => (
        <LabLink key={lab.slug} lab={lab} />
      ))}
      <SourceNote />
    </div>
  );
}

/** 全部外链实验，按学科分组。 */
export function RelatedLabsCatalog() {
  const [labs, setLabs] = useState<RelatedLab[] | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    void fetchRelatedLabs()
      .then(setLabs)
      .catch(() => setFailed(true));
  }, []);
  if (failed) return null;
  if (!labs) return <p className="text-sm">加载中…</p>;
  const groups = SUBJECT_ORDER.map((s) => labs.filter((l) => l.subject === s)).filter((g) => g.length > 0);
  return (
    <section className="space-y-3" data-testid="related-labs-catalog">
      <h2 className="text-lg font-semibold">更多实验 · WeduLab</h2>
      <SourceNote />
      {groups.map((g) => (
        <div key={g[0].subject} className="space-y-2">
          <div className="text-sm font-semibold">{g[0].subject_label}</div>
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {g.map((lab) => (
              <LabLink key={lab.slug} lab={lab} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}
