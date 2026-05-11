import { useEffect } from "react";
import { useParams } from "react-router-dom";

import { AgentDialogue } from "@/features/run/agent-dialogue";
import { BuildTimeline } from "@/features/run/build-timeline";
import { PreviewPane } from "@/features/run/preview-pane";
import { QaScorecard } from "@/features/run/qa-scorecard";
import { RevisePanel } from "@/features/run/revise-panel";
import { RunHeader } from "@/features/run/run-header";
import { useEventStream } from "@/hooks/use-event-stream";
import { useRunStore } from "@/store/run-store";

export function RunPage() {
  const params = useParams<{ id: string }>();
  const runId = params.id;
  useEventStream(runId);

  const failed = useRunStore((s) => s.status === "failed");
  const errorMessage = useRunStore((s) => s.errorMessage);

  useEffect(() => {
    if (!runId) return;
    document.title = `Run ${runId.slice(-8)} · AdFoundry`;
    return () => {
      document.title = "AdFoundry";
    };
  }, [runId]);

  if (!runId) {
    return (
      <p className="rounded-md border bg-card p-6 text-sm text-muted-foreground">
        Missing run id.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <RunHeader runId={runId} />

      {failed && errorMessage && (
        <div className="rounded-md border border-destructive/50 bg-destructive/10 px-4 py-3 text-sm text-destructive">
          Run failed: {errorMessage}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
        <aside className="lg:col-span-3 lg:sticky lg:top-20 lg:self-start">
          <BuildTimeline />
        </aside>

        <section className="lg:col-span-5">
          <div className="h-[calc(100vh-12rem)] min-h-[480px]">
            <AgentDialogue />
          </div>
        </section>

        <aside className="flex flex-col gap-4 lg:col-span-4">
          <PreviewPane runId={runId} />
          <QaScorecard />
        </aside>
      </div>

      <RevisePanel runId={runId} />
    </div>
  );
}
