import { useMemo } from "react";
import { Image as ImageIcon, Monitor, Smartphone } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { fileUrl } from "@/lib/api";
import { useRunStore } from "@/store/run-store";

interface PreviewPaneProps {
  runId: string;
}

export function PreviewPane({ runId }: PreviewPaneProps) {
  const render = useRunStore((s) => s.render);

  const iframeSrc = useMemo(() => {
    if (!render) return null;
    return fileUrl(runId, render.htmlPath);
  }, [render, runId]);

  const desktopUrl = render
    ? fileUrl(runId, render.desktopScreenshot)
    : null;
  const mobileUrl = render ? fileUrl(runId, render.mobileScreenshot) : null;

  return (
    <Card className="flex flex-col overflow-hidden">
      <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
        <div>
          <CardTitle className="text-base">HTML preview</CardTitle>
          <p className="text-xs text-muted-foreground">
            Rendered output, refreshed each generator attempt.
          </p>
        </div>
        {render && (
          <Badge variant="secondary" className="text-[11px]">
            Generator → attempt {render.attempt + 1}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-col gap-4 pt-0">
        <div className="overflow-hidden rounded-md border bg-muted/40">
          {iframeSrc ? (
            <iframe
              key={render?.refreshKey}
              src={iframeSrc}
              title="Campaign preview"
              className="h-[420px] w-full border-0 bg-white"
              sandbox="allow-same-origin"
            />
          ) : (
            <div className="flex h-[260px] flex-col items-center justify-center gap-2 text-sm text-muted-foreground">
              <ImageIcon className="h-6 w-6 opacity-60" />
              Awaiting first render…
            </div>
          )}
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Screenshot
            label="Desktop"
            url={desktopUrl}
            icon={<Monitor className="h-3.5 w-3.5" />}
          />
          <Screenshot
            label="Mobile"
            url={mobileUrl}
            icon={<Smartphone className="h-3.5 w-3.5" />}
          />
        </div>
      </CardContent>
    </Card>
  );
}

function Screenshot({
  label,
  url,
  icon,
}: {
  label: string;
  url: string | null;
  icon: React.ReactNode;
}) {
  return (
    <div className="overflow-hidden rounded-md border bg-muted/40">
      <div className="flex items-center justify-between border-b bg-background/60 px-2 py-1 text-[11px] font-medium text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          {icon}
          {label}
        </span>
      </div>
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="block">
          <img
            src={url}
            alt={`${label} screenshot`}
            className="block h-32 w-full object-cover object-top"
          />
        </a>
      ) : (
        <div className="grid h-32 place-items-center text-xs text-muted-foreground">
          —
        </div>
      )}
    </div>
  );
}
