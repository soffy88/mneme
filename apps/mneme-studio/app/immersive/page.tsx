"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { OEmptyState } from "@helios/blocks";
import { ProductNav } from "@/components/ProductNav";
import { ImmersiveWorkspace } from "@/components/immersive/ImmersiveWorkspace";
import {
  IMMERSIVE_MOCK,
  MOCK_MEDIA_ID,
  MOCK_SESSION_ID,
  generateMockSegments,
  immersiveApi,
  type ImmersiveMediaItem,
  type ImmersiveSegment,
  type ImmersiveSession,
} from "@/lib/immersive";
import { getStudentId, getToken, redirectToLogin } from "@/lib/mcp";

type LoadState =
  | { kind: "booting" }
  | { kind: "disabled" }
  | { kind: "error"; message: string }
  | {
      kind: "ready";
      studentId: string;
      mediaId: string;
      mediaTitle: string | null;
      mediaType: string;
      playbackUrl: string | null;
      segments: ImmersiveSegment[];
      session: ImmersiveSession | null;
      mediaList: ImmersiveMediaItem[];
      mock: boolean;
    };

function ImmersivePageInner() {
  const searchParams = useSearchParams();
  const wantedMedia = searchParams.get("media");
  const [state, setState] = useState<LoadState>({ kind: "booting" });

  useEffect(() => {
    let cancelled = false;

    void (async () => {
      // Mock mode: prove virtualization without backend / auth gate.
      if (IMMERSIVE_MOCK) {
        const segments = generateMockSegments(10_000);
        if (cancelled) return;
        setState({
          kind: "ready",
          studentId: "mock-student",
          mediaId: MOCK_MEDIA_ID,
          mediaTitle: "Mock Immersive Media (10k cues)",
          mediaType: "audio",
          playbackUrl: null,
          segments,
          session: {
            session_id: MOCK_SESSION_ID,
            media_id: MOCK_MEDIA_ID,
            playhead_ms: 0,
            current_segment_id: segments[0]?.segment_id ?? null,
            scaffold_level: 0,
            state: "ready",
            note: "mock continuity only",
          },
          mediaList: [],
          mock: true,
        });
        return;
      }

      if (!getToken() || !getStudentId()) {
        redirectToLogin();
        return;
      }

      setState({ kind: "booting" });
      try {
        const status = await immersiveApi.status();
        if (cancelled) return;
        if (!status.enabled) {
          setState({ kind: "disabled" });
          return;
        }

        const studentId = getStudentId()!;
        const listed = await immersiveApi.listMedia(studentId);
        const pick =
          listed.items.find((m) => m.media_id === wantedMedia) ??
          listed.items[0] ??
          null;

        if (!pick) {
          setState({
            kind: "ready",
            studentId,
            mediaId: "",
            mediaTitle: null,
            mediaType: "audio",
            playbackUrl: null,
            segments: [],
            session: null,
            mediaList: listed.items,
            mock: false,
          });
          return;
        }

        const [detail, segments, session] = await Promise.all([
          immersiveApi.getMedia(studentId, pick.media_id),
          immersiveApi.listAllSegments(studentId, pick.media_id),
          immersiveApi.openSession(studentId, pick.media_id),
        ]);

        if (cancelled) return;
        setState({
          kind: "ready",
          studentId,
          mediaId: pick.media_id,
          mediaTitle: detail.title ?? pick.title,
          mediaType: detail.media_type ?? pick.media_type,
          playbackUrl: detail.playback_url ?? null,
          segments,
          session,
          mediaList: listed.items,
          mock: false,
        });
      } catch (e) {
        if (cancelled) return;
        setState({
          kind: "error",
          message: e instanceof Error ? e.message : String(e),
        });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [wantedMedia]);

  const emptyMedia = useMemo(
    () => state.kind === "ready" && !state.mock && !state.mediaId,
    [state]
  );

  if (state.kind === "booting") {
    return (
      <main className="mx-auto max-w-5xl space-y-4 p-6" data-testid="immersive-root">
        <h1 className="text-2xl font-bold">Immersive Learning</h1>
        <ProductNav />
        <OEmptyState title="Loading…" description="Checking Immersive Learning status." />
      </main>
    );
  }

  if (state.kind === "disabled") {
    return (
      <main className="mx-auto max-w-5xl space-y-4 p-6" data-testid="immersive-root">
        <h1 className="text-2xl font-bold">Immersive Learning</h1>
        <ProductNav />
        <OEmptyState
          title="Immersive Learning is off"
          description="This feature is disabled by the server flag (IMMERSIVE_LEARNING_ENABLED)."
        />
      </main>
    );
  }

  if (state.kind === "error") {
    return (
      <main className="mx-auto max-w-5xl space-y-4 p-6" data-testid="immersive-root">
        <h1 className="text-2xl font-bold">Immersive Learning</h1>
        <ProductNav />
        <OEmptyState title="Could not open Immersive" description={state.message} />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl space-y-4 p-6" data-testid="immersive-root">
      <h1 className="text-2xl font-bold">Immersive Learning</h1>
      <ProductNav />

      {state.mediaList.length > 1 ? (
        <div className="flex flex-wrap gap-2 text-sm">
          {state.mediaList.map((m) => (
            <Link
              key={m.media_id}
              href={`/immersive?media=${encodeURIComponent(m.media_id)}`}
              className={`rounded-md border px-2.5 py-1 ${
                m.media_id === state.mediaId
                  ? "border-sky-500 bg-sky-50 dark:bg-sky-950"
                  : "border-neutral-200 hover:bg-neutral-50 dark:border-neutral-700"
              }`}
            >
              {m.title || m.media_id.slice(0, 8)}
            </Link>
          ))}
        </div>
      ) : null}

      {emptyMedia ? (
        <OEmptyState
          title="No media yet"
          description="Upload media via the Immersive API, then open this page with ?media=<id>."
        />
      ) : (
        <ImmersiveWorkspace
          key={state.mediaId || "empty"}
          studentId={state.studentId}
          mediaId={state.mediaId}
          mediaTitle={state.mediaTitle}
          mediaType={state.mediaType}
          playbackUrl={state.playbackUrl}
          segments={state.segments}
          initialPlayheadMs={state.session?.playhead_ms ?? 0}
          initialSegmentId={state.session?.current_segment_id ?? null}
          sessionId={state.session?.session_id ?? null}
          mock={state.mock}
        />
      )}
    </main>
  );
}

export default function ImmersivePage() {
  return (
    <Suspense
      fallback={
        <main className="mx-auto max-w-5xl space-y-4 p-6" data-testid="immersive-root">
          <h1 className="text-2xl font-bold">Immersive Learning</h1>
          <ProductNav />
          <OEmptyState title="Loading…" description="Checking Immersive Learning status." />
        </main>
      }
    >
      <ImmersivePageInner />
    </Suspense>
  );
}
