"use client";

import { useCallback, useState } from "react";
import {
  IMMERSIVE_MOCK,
  immersiveApi,
  type ImmersiveSegment,
  type PracticeResult,
} from "@/lib/immersive";

type PracticeMode = "dictation" | "listening" | "comprehension";

export interface PracticePanelProps {
  studentId: string;
  mediaId: string;
  sessionId: string | null;
  segment: ImmersiveSegment | null;
  mock?: boolean;
}

export function PracticePanel({
  studentId,
  mediaId,
  sessionId,
  segment,
  mock = IMMERSIVE_MOCK,
}: PracticePanelProps) {
  const [mode, setMode] = useState<PracticeMode>("dictation");
  const [draft, setDraft] = useState("");
  const [choice, setChoice] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PracticeResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const submit = useCallback(async () => {
    if (!segment) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      if (mock) {
        // Local-only feedback for mock mode — does not invent mastery.
        const ok =
          mode === "comprehension"
            ? choice === "a"
            : draft.trim().toLowerCase() === segment.text.trim().toLowerCase();
        setResult({
          score: {
            correctness: ok,
            partial_credit: ok ? 1 : 0.3,
            edit_distance: ok ? 0 : 3,
            verifier: "mock.local",
            verifier_version: "mock/1",
          },
        });
        return;
      }

      let res: PracticeResult;
      if (mode === "dictation") {
        res = await immersiveApi.practiceDictation(studentId, {
          media_id: mediaId,
          segment_id: segment.segment_id,
          submitted: draft,
          session_id: sessionId,
        });
      } else if (mode === "listening") {
        res = await immersiveApi.practiceListening(studentId, {
          media_id: mediaId,
          segment_id: segment.segment_id,
          submitted_meaning: draft,
          session_id: sessionId,
        });
      } else {
        // Comprehension: expected lives server-side when available; mock options for MVP UI.
        // Client only submits the chosen option id — never self-judges mastery.
        res = await immersiveApi.practiceComprehension(studentId, {
          media_id: mediaId,
          segment_id: segment.segment_id,
          expected_option_id: "a",
          submitted_option_id: choice || "b",
          session_id: sessionId,
          question_provenance: { source: "studio_mvp_placeholder" },
        });
      }
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [segment, mock, mode, choice, draft, studentId, mediaId, sessionId]);

  if (!segment) {
    return (
      <div className="rounded-lg border border-dashed border-neutral-300 p-4 text-sm text-neutral-500 dark:border-neutral-600">
        Select a sentence to practice.
      </div>
    );
  }

  return (
    <div
      className="space-y-3 rounded-lg border border-neutral-200 bg-white p-4 dark:border-neutral-700 dark:bg-neutral-900"
      data-testid="immersive-practice"
    >
      <div className="flex flex-wrap gap-2">
        {(
          [
            ["dictation", "Dictation"],
            ["listening", "Listening"],
            ["comprehension", "Comprehension"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`rounded-md px-2.5 py-1 text-sm ${
              mode === id
                ? "bg-sky-600 text-white"
                : "border border-neutral-200 hover:bg-neutral-50 dark:border-neutral-700 dark:hover:bg-neutral-800"
            }`}
            onClick={() => {
              setMode(id);
              setResult(null);
              setError(null);
            }}
          >
            {label}
          </button>
        ))}
      </div>

      <p className="text-xs text-neutral-500">
        Segment #{segment.order_index + 1} · mastery only from server practice APIs
      </p>

      {mode === "comprehension" ? (
        <fieldset className="space-y-2 text-sm">
          <legend className="mb-1 font-medium">What is the main meaning?</legend>
          {[
            { id: "a", label: "Closest paraphrase of the sentence" },
            { id: "b", label: "Unrelated meaning" },
            { id: "c", label: "Opposite meaning" },
          ].map((opt) => (
            <label key={opt.id} className="flex cursor-pointer items-center gap-2">
              <input
                type="radio"
                name="comp"
                value={opt.id}
                checked={choice === opt.id}
                onChange={() => setChoice(opt.id)}
              />
              {opt.label}
            </label>
          ))}
        </fieldset>
      ) : (
        <label className="block space-y-1 text-sm">
          <span className="font-medium">
            {mode === "dictation" ? "Type what you hear" : "Write the meaning"}
          </span>
          <textarea
            className="w-full rounded-md border border-neutral-200 bg-white p-2 text-sm dark:border-neutral-700 dark:bg-neutral-950"
            rows={3}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            placeholder={
              mode === "dictation"
                ? "Dictation answer…"
                : "Paraphrase / translation…"
            }
          />
        </label>
      )}

      <button
        type="button"
        disabled={busy || (mode === "comprehension" ? !choice : !draft.trim())}
        onClick={() => void submit()}
        className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-sky-700 disabled:opacity-40"
      >
        {busy ? "Submitting…" : "Submit"}
      </button>

      {error ? (
        <p className="text-sm text-red-600" role="alert">
          {error}
        </p>
      ) : null}

      {result ? (
        <div
          className={`rounded-md px-3 py-2 text-sm ${
            result.score.correctness
              ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-100"
              : "bg-amber-50 text-amber-900 dark:bg-amber-950 dark:text-amber-100"
          }`}
        >
          {result.score.correctness ? "Correct" : "Not quite"} · credit{" "}
          {result.score.partial_credit.toFixed(2)}
          {typeof result.score.edit_distance === "number"
            ? ` · edit ${result.score.edit_distance}`
            : ""}
        </div>
      ) : null}
    </div>
  );
}
