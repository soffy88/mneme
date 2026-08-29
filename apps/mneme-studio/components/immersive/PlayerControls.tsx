"use client";

const SPEEDS = [0.75, 1, 1.25, 1.5, 1.75, 2] as const;

export interface PlayerControlsProps {
  playing: boolean;
  loop: boolean;
  speed: number;
  showSubtitle: boolean;
  showTranslation: boolean;
  onPlayPause: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRepeat: () => void;
  onToggleLoop: () => void;
  onSpeedChange: (speed: number) => void;
  onToggleSubtitle: () => void;
  onToggleTranslation: () => void;
}

export function PlayerControls({
  playing,
  loop,
  speed,
  showSubtitle,
  showTranslation,
  onPlayPause,
  onPrev,
  onNext,
  onRepeat,
  onToggleLoop,
  onSpeedChange,
  onToggleSubtitle,
  onToggleTranslation,
}: PlayerControlsProps) {
  const btn =
    "rounded-md border border-neutral-200 bg-white px-2.5 py-1.5 text-sm hover:bg-neutral-50 disabled:opacity-40 dark:border-neutral-700 dark:bg-neutral-900 dark:hover:bg-neutral-800";
  const active = "border-sky-400 bg-sky-50 text-sky-800 dark:border-sky-600 dark:bg-sky-950 dark:text-sky-100";

  return (
    <div
      className="flex flex-wrap items-center gap-2 rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-700 dark:bg-neutral-900/60"
      data-testid="immersive-controls"
      role="toolbar"
      aria-label="Immersive player controls"
    >
      <button type="button" className={btn} onClick={onPrev} title="Previous (a / ←)">
        Prev
      </button>
      <button
        type="button"
        className={`${btn} min-w-20 font-medium`}
        onClick={onPlayPause}
        title="Play/Pause (Space / w)"
      >
        {playing ? "Pause" : "Play"}
      </button>
      <button type="button" className={btn} onClick={onNext} title="Next (d / →)">
        Next
      </button>
      <button type="button" className={btn} onClick={onRepeat} title="Repeat (s / ↓)">
        Repeat
      </button>
      <button
        type="button"
        className={`${btn} ${loop ? active : ""}`}
        onClick={onToggleLoop}
        title="Loop (r)"
        aria-pressed={loop}
      >
        Loop
      </button>

      <label className="ml-1 flex items-center gap-1 text-sm text-neutral-600 dark:text-neutral-300">
        Speed
        <select
          className="rounded border border-neutral-200 bg-white px-1.5 py-1 text-sm dark:border-neutral-700 dark:bg-neutral-900"
          value={speed}
          onChange={(e) => onSpeedChange(Number(e.target.value))}
          aria-label="Playback speed"
        >
          {SPEEDS.map((s) => (
            <option key={s} value={s}>
              {s}×
            </option>
          ))}
        </select>
      </label>

      <button
        type="button"
        className={`${btn} ${showSubtitle ? active : ""}`}
        onClick={onToggleSubtitle}
        title="Subtitle (e)"
        aria-pressed={showSubtitle}
      >
        EN
      </button>
      <button
        type="button"
        className={`${btn} ${showTranslation ? active : ""}`}
        onClick={onToggleTranslation}
        title="Translation (c)"
        aria-pressed={showTranslation}
      >
        译
      </button>

      <span className="ml-auto hidden text-xs text-neutral-400 sm:inline">
        a/d · s · Space · e/c · r
      </span>
    </div>
  );
}
