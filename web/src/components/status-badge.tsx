import { Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { RunStatus } from "@/types/api";

interface StatusBadgeProps {
  status: RunStatus;
  className?: string;
}

export function StatusBadge({ status, className }: StatusBadgeProps) {
  switch (status) {
    case "running":
      return (
        <Badge
          variant="outline"
          className={cn(
            "gap-1 border-blue-500/40 bg-blue-500/10 text-blue-700 dark:text-blue-300",
            className,
          )}
        >
          <Loader2 className="h-3 w-3 animate-spin" />
          Running
        </Badge>
      );
    case "completed":
      return (
        <Badge variant="success" className={className}>
          Completed
        </Badge>
      );
    case "failed":
      return (
        <Badge variant="destructive" className={className}>
          Failed
        </Badge>
      );
    case "unknown":
    default:
      return (
        <Badge variant="secondary" className={className}>
          Unknown
        </Badge>
      );
  }
}
