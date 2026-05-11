import { ShieldCheck, ShieldAlert, ShieldOff } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/store/run-store";
import type { IssueSeverity, QaReport } from "@/types/api";

const CATEGORIES: ReadonlyArray<{
  key: keyof QaReport;
  label: string;
}> = [
  { key: "visual_quality", label: "Visual quality" },
  { key: "brand_consistency", label: "Brand consistency" },
  { key: "readability", label: "Readability" },
  { key: "cta_visibility", label: "CTA visibility" },
  { key: "responsive_layout", label: "Responsive layout" },
  { key: "accessibility", label: "Accessibility" },
];

export function QaScorecard() {
  const qa = useRunStore((s) => s.qa);

  if (!qa) {
    return (
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">QA scorecard</CardTitle>
          <p className="text-xs text-muted-foreground">
            Visual QA hasn&apos;t reported yet.
          </p>
        </CardHeader>
        <CardContent>
          <Progress value={0} />
        </CardContent>
      </Card>
    );
  }

  const { report, attempt } = qa;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-2">
          <div>
            <CardTitle className="text-base">QA scorecard</CardTitle>
            <p className="text-xs text-muted-foreground">
              Attempt {attempt + 1} · {report.summary}
            </p>
          </div>
          <ApprovalBadge approved={report.approved} />
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <div className="mb-1 flex items-baseline justify-between">
            <span className="text-sm font-medium">Overall score</span>
            <span className="font-mono text-2xl font-semibold tabular-nums">
              {report.overall_score}
              <span className="ml-0.5 text-sm text-muted-foreground">/100</span>
            </span>
          </div>
          <Progress value={report.overall_score} className="h-2" />
        </div>

        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {CATEGORIES.map(({ key, label }) => (
            <CategoryBar
              key={key}
              label={label}
              value={report[key] as number}
            />
          ))}
        </div>

        {report.issues.length > 0 && (
          <div className="mt-2 flex flex-col gap-2">
            <h4 className="text-sm font-semibold">Issues</h4>
            <ul className="flex flex-col gap-2">
              {report.issues.map((issue, i) => (
                <IssueRow key={i} issue={issue} />
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CategoryBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round((value / 10) * 100);
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-semibold tabular-nums">{value}/10</span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  );
}

function ApprovalBadge({ approved }: { approved: boolean }) {
  return approved ? (
    <Badge variant="success" className="gap-1">
      <ShieldCheck className="h-3 w-3" />
      Approved
    </Badge>
  ) : (
    <Badge variant="warning" className="gap-1">
      <ShieldAlert className="h-3 w-3" />
      Open issues
    </Badge>
  );
}

const SEVERITY_DOT: Record<IssueSeverity, string> = {
  high: "bg-red-500",
  medium: "bg-amber-500",
  low: "bg-muted-foreground/40",
};

function IssueRow({ issue }: { issue: { severity: IssueSeverity; problem: string; recommended_fix: string } }) {
  return (
    <li className="rounded-md border bg-background p-3 text-sm">
      <div className="flex items-center gap-2">
        <span
          aria-hidden
          className={cn("h-2 w-2 rounded-full", SEVERITY_DOT[issue.severity])}
        />
        <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          {issue.severity}
        </span>
        {issue.severity === "high" && (
          <ShieldOff className="h-3.5 w-3.5 text-red-500" />
        )}
      </div>
      <p className="mt-1 leading-snug">{issue.problem}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        <span className="font-semibold text-foreground">Fix:</span>{" "}
        {issue.recommended_fix}
      </p>
    </li>
  );
}
