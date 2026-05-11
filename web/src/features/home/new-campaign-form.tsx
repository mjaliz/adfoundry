import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Rocket } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";

import { startRun } from "@/lib/api";
import { DEFAULT_BRIEF } from "@/types/api";
import type { CampaignBrief, RunMode } from "@/types/api";

const MODE_LABELS: Record<RunMode, { title: string; hint: string }> = {
  fixture: {
    title: "Fixture",
    hint: "Deterministic, no LLM calls — best for UI verification.",
  },
  hybrid: {
    title: "Hybrid",
    hint: "LLM where it matters, fixtures where it doesn't.",
  },
  live: {
    title: "Live",
    hint: "Full live agents (slower, requires API keys).",
  },
};

export function NewCampaignForm() {
  const navigate = useNavigate();
  const [brief, setBrief] = useState<CampaignBrief>(DEFAULT_BRIEF);
  const [mode, setMode] = useState<RunMode>("fixture");
  const [submitting, setSubmitting] = useState(false);

  const update = <K extends keyof CampaignBrief>(
    key: K,
    value: CampaignBrief[K],
  ) => {
    setBrief((prev) => ({ ...prev, [key]: value }));
  };

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (submitting) return;
    setSubmitting(true);
    try {
      const { run_id } = await startRun(brief, mode);
      toast.success("Run started", { description: run_id });
      navigate(`/runs/${run_id}`);
    } catch (err) {
      toast.error("Failed to start run", {
        description: err instanceof Error ? err.message : "Unknown error",
      });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={onSubmit} className="grid gap-4">
      <div className="grid gap-2">
        <Label htmlFor="url">Landing page URL</Label>
        <Input
          id="url"
          required
          inputMode="url"
          value={brief.url}
          onChange={(e) => update("url", e.target.value)}
          placeholder="https://www.nike.com"
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="theme">Theme</Label>
          <Input
            id="theme"
            required
            value={brief.theme}
            onChange={(e) => update("theme", e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="campaign_type">Campaign type</Label>
          <Input
            id="campaign_type"
            required
            value={brief.campaign_type}
            onChange={(e) => update("campaign_type", e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="audience">Audience</Label>
          <Input
            id="audience"
            required
            value={brief.audience}
            onChange={(e) => update("audience", e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="tone">Tone</Label>
          <Input
            id="tone"
            required
            value={brief.tone}
            onChange={(e) => update("tone", e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div className="grid gap-2">
          <Label htmlFor="offer">Offer</Label>
          <Input
            id="offer"
            required
            value={brief.offer}
            onChange={(e) => update("offer", e.target.value)}
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor="cta_preference">CTA preference</Label>
          <Input
            id="cta_preference"
            required
            value={brief.cta_preference}
            onChange={(e) => update("cta_preference", e.target.value)}
          />
        </div>
      </div>

      <div className="grid gap-2">
        <Label htmlFor="goal">Goal</Label>
        <Textarea
          id="goal"
          required
          rows={2}
          value={brief.goal}
          onChange={(e) => update("goal", e.target.value)}
        />
      </div>

      <div className="grid gap-2">
        <Label htmlFor="mode">Mode</Label>
        <Select value={mode} onValueChange={(v) => setMode(v as RunMode)}>
          <SelectTrigger id="mode">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(["fixture", "hybrid", "live"] as const).map((opt) => (
              <SelectItem key={opt} value={opt}>
                <div className="flex flex-col">
                  <span className="font-medium">{MODE_LABELS[opt].title}</span>
                  <span className="text-xs text-muted-foreground">
                    {MODE_LABELS[opt].hint}
                  </span>
                </div>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-xs text-muted-foreground">
          {MODE_LABELS[mode].hint}
        </p>
      </div>

      <Button type="submit" disabled={submitting} className="w-full sm:w-auto">
        <Rocket className="h-4 w-4" />
        {submitting ? "Starting…" : "Start campaign run"}
      </Button>
    </form>
  );
}
