"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  IMMERSIVE_MOCK,
  immersiveApi,
  type ImmersiveSegment,
} from "@/lib/immersive";
import { PlayerControls } from "./PlayerControls";
import { PracticePanel } from "./PracticePanel";
import { TranscriptList } from "./TranscriptList";

export interface ImmersiveWorkspaceProps {
  studentId: string;
  mediaId: string;
  mediaTitle?: string | null;
  mediaType?: string;
  playbackUrl?: string | null;
  segments: ImmersiveSegment[];
  /** Session resume playhead from server (continuity only — not mastery). */
  initialPlayheadMs?: number;
  initialSegmentId?: string | null;
  sessionId?: string | null;
  mock?: boolean;
}

function indexFromPlayhead(
  segments: ImmersiveSegment[],
  playheadMs: number
): number {
  if (segments.length === 0) return 0;
  for (let i = 0; i < segments.length; i++) {
    if (playheadMs < segments[i].end_ms) return i;
  }
  return segments.length - 1;
}

function indexFromSegmentId(
  segments: ImmersiveSegment[],
  segmentId: string | null | undefined
): number | null {
  if (!segmentId) return null;
  const i = segments.findIndex((s) => s.segment_id === segmentId);
  return i >= 0 ? i : null;
}

export function ImmersiveWorkspace({
  studentId,
  mediaId,
  mediaTitle,
  mediaType = "audio",
  playbackUrl,
  segments,
  initialPlayheadMs = 0,
  initialSegmentId = null,
  sessionId: sessionIdProp = null,
  mock = IMMERSIVE_MOCK,
}: ImmersiveWorkspaceProps) {
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(sessionIdProp);
  const [currentIndex, setCurrentIndex] = useState(() => {
    const byId = indexFromSegmentId(segments, initialSegmentId);
    if (byId != null) return byId;
    return indexFromPlayhead(segments, initialPlayheadMs);
  });
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showSubtitle, setShowSubtitle] = useState(true);
  const [showTranslation, setShowTranslation] = useState(false);
  const [playheadMs, setPlayheadMs] = useState(initialPlayheadMs);
  const mockClockRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const current = segments[currentIndex] ?? null;

  // Open / resume session on mount (skipped in mock).
  useEffect(() => {
    if (mock || sessionId || !studentId || !mediaId) return;
    let cancelled = false;
    void (async () => {
      try {
        const session = await immersiveApi.openSession(studentId, mediaId);
        if (cancelled) return;
        setSessionId(session.session_id);
        const byId = indexFromSegmentId(segments, session.current_segment_id);
        if (byId != null) setCurrentIndex(byId);
        else if (session.playhead_ms > 0) {
          setCurrentIndex(indexFromPlayhead(segments, session.playhead_ms));
          setPlayheadMs(session.playhead_ms);
        }
      } catch {
        // Player remains usable without continuity persistence.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [mock, sessionId, studentId, mediaId, segments]);

  // Periodic playhead PATCH (continuity only).
  useEffect(() => {
    if (mock || !sessionId || !studentId) return;
    const id = setInterval(() => {
      const seg = segments[currentIndex];
      void immersiveApi
        .patchSession(studentId, sessionId, {
          playhead_ms: Math.round(playheadMs),
          current_segment_id: seg?.segment_id ?? null,
          state: playing ? "playing" : "paused",
        })
        .catch(() => undefined);
    }, 4000);
    return () => clearInterval(id);
  }, [mock, sessionId, studentId, playheadMs, currentIndex, playing, segments]);

  const seekToIndex = useCallback(
    (index: number, autoplay = true) => {
      if (segments.length === 0) return;
      const next = Math.max(0, Math.min(segments.length - 1, index));
      setCurrentIndex(next);
      const seg = segments[next];
      setPlayheadMs(seg.start_ms);
      const el = mediaRef.current;
      if (el && playbackUrl) {
        el.currentTime = seg.start_ms / 1000;
        if (autoplay) {
          void el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
        }
      } else if (autoplay) {
        setPlaying(true);
      }
    },
    [segments, playbackUrl]
  );

  const playPause = useCallback(() => {
    const el = mediaRef.current;
    if (el && playbackUrl) {
      if (el.paused) {
        void el.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
      } else {
        el.pause();
        setPlaying(false);
      }
      return;
    }
    setPlaying((p) => !p);
  }, [playbackUrl]);

  const repeatCurrent = useCallback(() => {
    seekToIndex(currentIndex, true);
  }, [seekToIndex, currentIndex]);

  const goPrev = useCallback(() => seekToIndex(currentIndex - 1), [seekToIndex, currentIndex]);
  const goNext = useCallback(() => seekToIndex(currentIndex + 1), [seekToIndex, currentIndex]);

  // Apply playback rate.
  useEffect(() => {
    const el = mediaRef.current;
    if (el) el.playbackRate = speed;
  }, [speed]);

  // Mock / no-URL clock: advance playhead and auto-advance segments.
  useEffect(() => {
    if (!playing) {
      if (mockClockRef.current != null) {
        clearInterval(mockClockRef.current);
        mockClockRef.current = null;
      }
      return;
    }
    if (playbackUrl && mediaRef.current) return;

    mockClockRef.current = setInterval(() => {
      setPlayheadMs((ms) => {
        const seg = segments[currentIndex];
        if (!seg) return ms;
        const next = ms + 100 * speed;
        if (next >= seg.end_ms) {
          if (loop) {
            setTimeout(() => seekToIndex(currentIndex, true), 0);
            return seg.start_ms;
          }
          if (currentIndex < segments.length - 1) {
            setTimeout(() => seekToIndex(currentIndex + 1, true), 0);
          } else {
            setPlaying(false);
          }
          return seg.end_ms;
        }
        return next;
      });
    }, 100);

    return () => {
      if (mockClockRef.current != null) {
        clearInterval(mockClockRef.current);
        mockClockRef.current = null;
      }
    };
  }, [playing, playbackUrl, speed, currentIndex, segments, loop, seekToIndex]);

  // Sync playhead from real media element.
  useEffect(() => {
    const el = mediaRef.current;
    if (!el || !playbackUrl) return;

    const onTime = () => {
      const ms = el.currentTime * 1000;
      setPlayheadMs(ms);
      const seg = segments[currentIndex];
      if (!seg) return;
      if (ms >= seg.end_ms - 20) {
        if (loop) {
          el.currentTime = seg.start_ms / 1000;
          void el.play();
          return;
        }
        if (currentIndex < segments.length - 1) {
          seekToIndex(currentIndex + 1, true);
        } else {
          el.pause();
          setPlaying(false);
        }
      } else if (ms < seg.start_ms - 50 || ms > seg.end_ms + 50) {
        // External seek — snap index to playhead.
        setCurrentIndex(indexFromPlayhead(segments, ms));
      }
    };
    const onPlay = () => setPlaying(true);
    const onPause = () => setPlaying(false);

    el.addEventListener("timeupdate", onTime);
    el.addEventListener("play", onPlay);
    el.addEventListener("pause", onPause);
    return () => {
      el.removeEventListener("timeupdate", onTime);
      el.removeEventListener("play", onPlay);
      el.removeEventListener("pause", onPause);
    };
  }, [playbackUrl, currentIndex, segments, loop, seekToIndex]);

  // Keyboard-first map (independent; not copied from DashPlayer).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.tagName === "SELECT" ||
          t.isContentEditable)
      ) {
        return;
      }
      const key = e.key;
      if (key === " " || key === "w" || key === "W") {
        e.preventDefault();
        playPause();
      } else if (key === "a" || key === "A" || key === "ArrowLeft") {
        e.preventDefault();
        goPrev();
      } else if (key === "d" || key === "D" || key === "ArrowRight") {
        e.preventDefault();
        goNext();
      } else if (key === "s" || key === "S" || key === "ArrowDown") {
        e.preventDefault();
        repeatCurrent();
      } else if (key === "e" || key === "E") {
        e.preventDefault();
        setShowSubtitle((v) => !v);
      } else if (key === "c" || key === "C") {
        e.preventDefault();
        setShowTranslation((v) => !v);
      } else if (key === "r" || key === "R") {
        e.preventDefault();
        setLoop((v) => !v);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [playPause, goPrev, goNext, repeatCurrent]);

  const isVideo = mediaType === "video" || Boolean(playbackUrl?.match(/\.(mp4|webm|mov)(\?|$)/i));

  const cueLabel = useMemo(() => {
    if (!current) return "—";
    return `#${currentIndex + 1} · ${(playheadMs / 1000).toFixed(1)}s`;
  }, [current, currentIndex, playheadMs]);

  return (
    <div className="space-y-4" data-testid="immersive-workspace">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold">{mediaTitle || "Immersive media"}</h2>
        <span className="text-xs text-neutral-500">{cueLabel}</span>
      </div>

      <div className="overflow-hidden rounded-lg border border-neutral-200 bg-black dark:border-neutral-700">
        {playbackUrl ? (
          isVideo ? (
            <video
              ref={(n) => {
                mediaRef.current = n;
              }}
              src={playbackUrl}
              className="aspect-video w-full"
              controls={false}
              playsInline
            />
          ) : (
            <div className="flex aspect-video w-full flex-col items-center justify-center gap-3 bg-neutral-900 p-6 text-neutral-200">
              <audio
                ref={(n) => {
                  mediaRef.current = n;
                }}
                src={playbackUrl}
                className="w-full max-w-md"
              />
              <p className="text-sm opacity-80">Audio · {cueLabel}</p>
              {showSubtitle && current ? (
                <p
                  data-testid="immersive-current-segment"
                  className="max-w-xl text-center text-lg"
                >
                  {current.text}
                </p>
              ) : null}
              {showTranslation && current?.translated_text ? (
                <p className="max-w-xl text-center text-sm text-neutral-400">
                  {current.translated_text}
                </p>
              ) : null}
            </div>
          )
        ) : (
          <div className="flex aspect-video w-full flex-col items-center justify-center gap-2 bg-neutral-900 p-6 text-neutral-200">
            <p className="text-sm text-neutral-400">
              {mock ? "Mock player (timer-driven)" : "No playback URL"}
            </p>
            {showSubtitle && current ? (
              <p
                data-testid="immersive-current-segment"
                className="max-w-xl text-center text-lg"
              >
                {current.text}
              </p>
            ) : null}
            {showTranslation && current?.translated_text ? (
              <p className="max-w-xl text-center text-sm text-neutral-400">
                {current.translated_text}
              </p>
            ) : null}
          </div>
        )}
      </div>

      <PlayerControls
        playing={playing}
        loop={loop}
        speed={speed}
        showSubtitle={showSubtitle}
        showTranslation={showTranslation}
        onPlayPause={playPause}
        onPrev={goPrev}
        onNext={goNext}
        onRepeat={repeatCurrent}
        onToggleLoop={() => setLoop((v) => !v)}
        onSpeedChange={setSpeed}
        onToggleSubtitle={() => setShowSubtitle((v) => !v)}
        onToggleTranslation={() => setShowTranslation((v) => !v)}
      />

      <div className="grid gap-4 lg:grid-cols-5">
        <div className="lg:col-span-3">
          <TranscriptList
            segments={segments}
            currentIndex={currentIndex}
            showSubtitle={showSubtitle}
            showTranslation={showTranslation}
            onSeek={(i) => seekToIndex(i, true)}
          />
        </div>
        <div className="lg:col-span-2">
          <PracticePanel
            studentId={studentId}
            mediaId={mediaId}
            sessionId={sessionId}
            segment={current}
            mock={mock}
          />
        </div>
      </div>
    </div>
  );
}
