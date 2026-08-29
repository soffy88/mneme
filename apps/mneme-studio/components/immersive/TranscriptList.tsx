"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ImmersiveSegment } from "@/lib/immersive";

const ROW_HEIGHT = 56;
const OVERSCAN = 12;

export interface TranscriptListProps {
  segments: ImmersiveSegment[];
  currentIndex: number;
  showSubtitle: boolean;
  showTranslation: boolean;
  onSeek: (index: number) => void;
  height?: number;
}

export function TranscriptList({
  segments,
  currentIndex,
  showSubtitle,
  showTranslation,
  onSeek,
  height = 420,
}: TranscriptListProps) {
  const scrollerRef = useRef<HTMLDivElement>(null);
  const [scrollTop, setScrollTop] = useState(0);
  const followRef = useRef(true);

  const totalHeight = segments.length * ROW_HEIGHT;
  const visibleCount = Math.ceil(height / ROW_HEIGHT);

  const { start, end } = useMemo(() => {
    const rawStart = Math.floor(scrollTop / ROW_HEIGHT);
    const s = Math.max(0, rawStart - OVERSCAN);
    const e = Math.min(segments.length, rawStart + visibleCount + OVERSCAN);
    return { start: s, end: e };
  }, [scrollTop, segments.length, visibleCount]);

  const slice = segments.slice(start, end);

  // Keep current cue in view when following playback.
  useEffect(() => {
    if (!followRef.current || !scrollerRef.current) return;
    const top = currentIndex * ROW_HEIGHT;
    const viewBottom = scrollTop + height;
    if (top < scrollTop || top + ROW_HEIGHT > viewBottom) {
      const next = Math.max(0, top - height / 3);
      scrollerRef.current.scrollTop = next;
      setScrollTop(next);
    }
  }, [currentIndex, height, scrollTop]);

  const onScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setScrollTop(el.scrollTop);
    // User scroll detaches follow until they click a cue or current exits view.
    const top = currentIndex * ROW_HEIGHT;
    const inView =
      top >= el.scrollTop - ROW_HEIGHT &&
      top <= el.scrollTop + height + ROW_HEIGHT;
    if (!inView) followRef.current = false;
  }, [currentIndex, height]);

  const handleClick = useCallback(
    (index: number) => {
      followRef.current = true;
      onSeek(index);
    },
    [onSeek]
  );

  return (
    <div
      className="rounded-lg border border-neutral-200 bg-white dark:border-neutral-700 dark:bg-neutral-900"
      data-testid="immersive-transcript"
    >
      <div className="flex items-center justify-between border-b border-neutral-100 px-3 py-2 text-xs text-neutral-500 dark:border-neutral-800">
        <span>Transcript · {segments.length.toLocaleString()} cues</span>
        <button
          type="button"
          className="rounded px-2 py-0.5 hover:bg-neutral-100 dark:hover:bg-neutral-800"
          onClick={() => {
            followRef.current = true;
            if (scrollerRef.current) {
              const next = Math.max(0, currentIndex * ROW_HEIGHT - height / 3);
              scrollerRef.current.scrollTop = next;
              setScrollTop(next);
            }
          }}
        >
          Follow
        </button>
      </div>
      <div
        ref={scrollerRef}
        onScroll={onScroll}
        className="overflow-y-auto"
        style={{ height }}
        role="listbox"
        aria-label="Transcript segments"
      >
        <div style={{ height: totalHeight, position: "relative" }}>
          {slice.map((seg, i) => {
            const index = start + i;
            const active = index === currentIndex;
            return (
              <button
                key={seg.segment_id}
                type="button"
                role="option"
                aria-selected={active}
                onClick={() => handleClick(index)}
                className={`absolute left-0 right-0 flex w-full flex-col justify-center border-b border-neutral-50 px-3 text-left transition-colors dark:border-neutral-800 ${
                  active
                    ? "bg-sky-50 dark:bg-sky-950"
                    : "hover:bg-neutral-50 dark:hover:bg-neutral-800/60"
                }`}
                style={{ top: index * ROW_HEIGHT, height: ROW_HEIGHT }}
              >
                <span className="truncate text-xs text-neutral-400">
                  #{index + 1}
                  {seg.speaker ? ` · ${seg.speaker}` : ""}
                </span>
                {showSubtitle ? (
                  <span
                    className={`truncate text-sm ${
                      active ? "font-medium text-sky-900 dark:text-sky-100" : ""
                    }`}
                  >
                    {seg.text}
                  </span>
                ) : (
                  <span className="truncate text-sm text-neutral-400">••••</span>
                )}
                {showTranslation && seg.translated_text ? (
                  <span className="truncate text-xs text-neutral-500">
                    {seg.translated_text}
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
