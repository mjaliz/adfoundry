import { useEffect, useState } from "react";

import { eventStreamUrl } from "@/lib/api";
import { useRunStore } from "@/store/run-store";
import type { RunEvent, RunEventType } from "@/types/events";
import { RUN_EVENT_TYPES } from "@/types/events";

export type StreamPhase = "idle" | "connecting" | "open" | "closed" | "error";

/**
 * Subscribe to a run's SSE stream and pipe each typed event into useRunStore.
 *
 * The backend emits one named SSE event per RunEventType plus the canonical
 * JSON payload — so we subscribe to each named channel and dispatch through
 * a shared parser. Replay-then-tail behavior is provided by the server.
 */
export function useEventStream(runId: string | undefined): StreamPhase {
  const apply = useRunStore((s) => s.apply);
  const reset = useRunStore((s) => s.reset);
  const [phase, setPhase] = useState<StreamPhase>("idle");

  useEffect(() => {
    if (!runId) {
      setPhase("idle");
      return;
    }
    reset(runId);
    setPhase("connecting");
    const source = new EventSource(eventStreamUrl(runId));

    const handle = (raw: MessageEvent) => {
      try {
        const parsed = JSON.parse(raw.data) as RunEvent;
        apply(parsed);
      } catch (err) {
        // Malformed frame — log and continue. The stream remains valid.
        console.warn("Failed to parse SSE frame", err, raw.data);
      }
    };

    const types: RunEventType[] = [...RUN_EVENT_TYPES];
    for (const type of types) {
      source.addEventListener(type, handle as EventListener);
    }
    // Fallback for unnamed `message` events (none expected, but defensive).
    source.addEventListener("message", handle as EventListener);

    source.onopen = () => setPhase("open");
    source.onerror = () => {
      // Browsers automatically retry; we surface the state but keep the
      // listener attached. If the server already closed the stream the
      // readyState becomes CLOSED.
      setPhase(source.readyState === EventSource.CLOSED ? "closed" : "error");
    };

    return () => {
      for (const type of types) {
        source.removeEventListener(type, handle as EventListener);
      }
      source.removeEventListener("message", handle as EventListener);
      source.close();
      setPhase("closed");
    };
  }, [runId, apply, reset]);

  return phase;
}
