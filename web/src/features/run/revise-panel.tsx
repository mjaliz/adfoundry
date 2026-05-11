import { useState } from "react";
import { Loader2, Send } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, submitRevision } from "@/lib/api";
import { useRunStore } from "@/store/run-store";

interface RevisePanelProps {
  runId: string;
}

export function RevisePanel({ runId }: RevisePanelProps) {
  const status = useRunStore((s) => s.status);
  const beginRevision = useRunStore((s) => s.beginRevision);
  const [feedback, setFeedback] = useState("");
  const isRevising = status === "revising";
  const canSubmit = !isRevising && feedback.trim().length > 0;

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    const trimmed = feedback.trim();
    if (!trimmed || isRevising) return;
    beginRevision();
    try {
      await submitRevision(runId, trimmed);
      setFeedback("");
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.status === 409
            ? "A revision is already running for this campaign."
            : err.message
          : "Could not start the revision. Please try again.";
      toast.error(message);
    }
  };

  if (status !== "completed" && status !== "revising") {
    return null;
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Revise this campaign</CardTitle>
        <CardDescription>
          Tell the agents what to change. They&apos;ll re-engage the dialogue
          with your feedback as a Director instruction; the existing brief,
          brand kit, strategy, copy, and hero stay frozen.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3">
          <Textarea
            value={feedback}
            onChange={(e) => setFeedback(e.target.value)}
            placeholder="e.g. Make the headline punchier and swap the hero to a deeper blue."
            rows={3}
            disabled={isRevising}
            aria-label="Revision feedback"
          />
          <div className="flex items-center justify-end gap-2">
            <Button type="submit" disabled={!canSubmit} className="gap-1.5">
              {isRevising ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Revising…
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" />
                  Submit revision
                </>
              )}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
