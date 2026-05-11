import { Link } from "react-router-dom";
import { ArrowLeft, Clock, Download } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/components/status-badge";
import { useRunStore } from "@/store/run-store";
import { useElapsed } from "@/hooks/use-elapsed";
import { packageZipUrl } from "@/lib/api";
import { shortRunId } from "@/lib/format";

interface RunHeaderProps {
  runId: string;
}

export function RunHeader({ runId }: RunHeaderProps) {
  const status = useRunStore((s) => s.status);
  const mode = useRunStore((s) => s.mode);
  const brief = useRunStore((s) => s.brief);
  const startedAt = useRunStore((s) => s.startedAt);
  const completedAt = useRunStore((s) => s.completedAt);
  const overall = useRunStore((s) => s.overallScore);

  const elapsed = useElapsed(startedAt, completedAt);

  return (
    <div className="flex flex-col gap-3 rounded-xl border bg-card p-4 shadow-sm">
      <div className="flex flex-wrap items-center gap-3">
        <Button asChild variant="ghost" size="sm" className="gap-1.5 px-2">
          <Link to="/">
            <ArrowLeft className="h-4 w-4" /> All runs
          </Link>
        </Button>
        <span className="font-mono text-sm font-semibold">
          {shortRunId(runId)}
        </span>
        <StatusBadge status={status} />
        {mode && (
          <Badge variant="outline" className="capitalize">
            {mode}
          </Badge>
        )}
        {brief?.theme && <Badge variant="secondary">{brief.theme}</Badge>}
        {status === "completed" && (
          <Button asChild size="sm" variant="secondary" className="ml-auto gap-1.5">
            <a
              href={packageZipUrl(runId)}
              download={`${runId}.zip`}
              rel="noopener"
            >
              <Download className="h-4 w-4" />
              Download package
            </a>
          </Button>
        )}
        <span
          className={`${
            status === "completed" ? "" : "ml-auto "
          }inline-flex items-center gap-1.5 font-mono text-xs text-muted-foreground tabular-nums`}
        >
          <Clock className="h-3.5 w-3.5" />
          {elapsed}
        </span>
        {typeof overall === "number" && (
          <Badge variant="success" className="font-mono">
            {overall}/100
          </Badge>
        )}
      </div>
      {brief && (
        <div className="grid gap-2 text-xs text-muted-foreground sm:grid-cols-2 md:grid-cols-3">
          <BriefField label="URL" value={brief.url} mono />
          <BriefField label="Audience" value={brief.audience} />
          <BriefField label="Tone" value={brief.tone} />
          <BriefField label="Offer" value={brief.offer} />
          <BriefField label="CTA" value={brief.cta_preference} />
          <BriefField label="Goal" value={brief.goal} />
        </div>
      )}
    </div>
  );
}

function BriefField({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground/70">
        {label}
      </span>
      <span
        className={mono ? "truncate font-mono text-foreground" : "truncate text-foreground"}
        title={value}
      >
        {value}
      </span>
    </div>
  );
}
