import { Check, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useRunStore } from "@/store/run-store";
import { cn } from "@/lib/utils";
import { titleCase } from "@/lib/format";
import type { NodeProgress, NodeState } from "@/store/run-store";
import type { WorkflowNode } from "@/types/api";
import { WORKFLOW_NODE_ORDER } from "@/types/api";

const NODE_LABELS: Record<WorkflowNode, string> = {
  research: "Research",
  brand: "Brand kit",
  strategy: "Strategy",
  creative: "Creative",
  image_asset: "Hero image",
  dialogue: "Generator + QA dialogue",
  package: "Package",
};

export function BuildTimeline() {
  const nodes = useRunStore((s) => s.nodes);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Build timeline</CardTitle>
      </CardHeader>
      <CardContent className="px-0 pb-2">
        <ol className="flex flex-col">
          {WORKFLOW_NODE_ORDER.map((node, idx) => (
            <TimelineRow
              key={node}
              node={node}
              state={nodes[node]}
              isLast={idx === WORKFLOW_NODE_ORDER.length - 1}
            />
          ))}
        </ol>
      </CardContent>
    </Card>
  );
}

interface TimelineRowProps {
  node: WorkflowNode;
  state: NodeState;
  isLast: boolean;
}

function TimelineRow({ node, state, isLast }: TimelineRowProps) {
  return (
    <li className="relative px-6 py-3">
      {!isLast && (
        <span
          aria-hidden
          className={cn(
            "absolute left-[1.875rem] top-9 h-[calc(100%-1.5rem)] w-px",
            state.status === "done" ? "bg-emerald-500/40" : "bg-border",
          )}
        />
      )}
      <div className="flex items-start gap-3">
        <Dot status={state.status} />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 text-sm font-medium">
            {NODE_LABELS[node] ?? titleCase(node)}
          </div>
          {state.summary ? (
            <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
              {state.summary}
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-muted-foreground/70">
              {state.status === "running" ? "Working…" : "Pending"}
            </p>
          )}
          {state.status === "running" && <ProgressLine node={node} />}
        </div>
      </div>
    </li>
  );
}

/**
 * Per-row subscriber — selects only this node's progress entry so a high-rate
 * delta on one row does not re-render the other timeline rows.
 */
function ProgressLine({ node }: { node: WorkflowNode }) {
  const progress = useRunStore((s) => s.nodeProgress[node]);
  if (!progress || !progress.text) return null;
  return <ProgressBody progress={progress} />;
}

function ProgressBody({ progress }: { progress: NodeProgress }) {
  if (progress.kind === "status") {
    return (
      <p className="mt-1 line-clamp-3 text-xs text-muted-foreground/90">
        <span className="mr-1 text-muted-foreground/60">•</span>
        {progress.text}
      </p>
    );
  }
  return (
    <p className="mt-1 line-clamp-4 whitespace-pre-wrap break-words text-xs italic leading-relaxed text-muted-foreground/90">
      {progress.text}
      <span
        aria-hidden
        className="ml-0.5 inline-block h-2.5 w-0.5 translate-y-0.5 animate-pulse bg-current opacity-70"
      />
    </p>
  );
}

function Dot({ status }: { status: NodeState["status"] }) {
  if (status === "running") {
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-blue-500/15 text-blue-600 dark:text-blue-300">
        <Loader2 className="h-3 w-3 animate-spin" />
      </span>
    );
  }
  if (status === "done") {
    return (
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-emerald-500/15 text-emerald-600 dark:text-emerald-300">
        <Check className="h-3.5 w-3.5" />
      </span>
    );
  }
  return (
    <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full border border-dashed border-border">
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/40" />
    </span>
  );
}
