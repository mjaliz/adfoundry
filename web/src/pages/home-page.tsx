import { useEffect } from "react";
import { Link } from "react-router-dom";
import { RotateCw } from "lucide-react";

import { NewCampaignForm } from "@/features/home/new-campaign-form";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { StatusBadge } from "@/components/status-badge";
import { useRunsListStore } from "@/store/runs-list-store";
import { formatRelative, shortRunId } from "@/lib/format";

export function HomePage() {
  const runs = useRunsListStore((s) => s.runs);
  const loading = useRunsListStore((s) => s.loading);
  const error = useRunsListStore((s) => s.error);
  const refresh = useRunsListStore((s) => s.refresh);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => {
      void refresh();
    }, 5_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_380px]">
      <section>
        <Card>
          <CardHeader>
            <CardTitle>New campaign</CardTitle>
            <CardDescription>
              Brief the agent crew on the brand, theme, and offer. They&apos;ll
              research, strategize, write, render, and QA — live.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <NewCampaignForm />
          </CardContent>
        </Card>
      </section>

      <aside className="lg:sticky lg:top-20 lg:self-start">
        <Card className="flex h-[calc(100vh-7rem)] flex-col">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-base">Run history</CardTitle>
                <CardDescription className="text-xs">
                  {runs.length} {runs.length === 1 ? "run" : "runs"} on disk
                </CardDescription>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={() => void refresh()}
                aria-label="Refresh run list"
              >
                <RotateCw
                  className={loading ? "h-4 w-4 animate-spin" : "h-4 w-4"}
                />
              </Button>
            </div>
          </CardHeader>
          <Separator />
          <ScrollArea className="flex-1">
            <div className="flex flex-col">
              {error && (
                <p className="px-6 py-4 text-sm text-destructive">{error}</p>
              )}
              {!error && runs.length === 0 && !loading && (
                <p className="px-6 py-4 text-sm text-muted-foreground">
                  No runs yet. Start one on the left.
                </p>
              )}
              {runs.map((run) => (
                <Link
                  key={run.run_id}
                  to={`/runs/${run.run_id}`}
                  className="group flex flex-col gap-1 px-6 py-3 text-sm transition-colors hover:bg-accent"
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-xs font-medium">
                      {shortRunId(run.run_id)}
                    </span>
                    <StatusBadge status={run.status} />
                  </div>
                  <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span className="truncate">
                      {run.theme ?? "—"} · {run.mode ?? "?"}
                    </span>
                    <span>{formatRelative(run.created_at)}</span>
                  </div>
                  {typeof run.overall_score === "number" && (
                    <div className="text-xs text-muted-foreground">
                      Score{" "}
                      <span className="font-semibold text-foreground">
                        {run.overall_score}
                      </span>
                      /100
                    </div>
                  )}
                </Link>
              ))}
            </div>
          </ScrollArea>
        </Card>
      </aside>
    </div>
  );
}
