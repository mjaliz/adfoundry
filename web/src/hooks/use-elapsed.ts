import { useEffect, useState } from "react";

import { formatElapsed } from "@/lib/format";

/**
 * Tick once per second to render an elapsed timer between `startedAt` and
 * `endedAt` (or now). Returns a formatted "M:SS" string.
 */
export function useElapsed(
  startedAt: string | null,
  endedAt: string | null,
): string {
  const [, setTick] = useState(0);

  useEffect(() => {
    if (!startedAt || endedAt) return;
    const id = window.setInterval(() => setTick((t) => t + 1), 1_000);
    return () => window.clearInterval(id);
  }, [startedAt, endedAt]);

  if (!startedAt) return "0:00";
  const start = Date.parse(startedAt);
  const end = endedAt ? Date.parse(endedAt) : Date.now();
  return formatElapsed(end - start);
}
