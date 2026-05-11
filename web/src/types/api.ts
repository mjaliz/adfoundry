// API contracts mirrored from adfoundry/server.py + models.py.
// Keep in sync with the Python schema.

export type RunMode = "fixture" | "hybrid" | "live";

export type RunStatus = "running" | "completed" | "failed" | "unknown";

export interface CampaignBrief {
  url: string;
  campaign_type: string;
  goal: string;
  theme: string;
  audience: string;
  tone: string;
  offer: string;
  cta_preference: string;
}

export interface RunSummary {
  run_id: string;
  created_at: string | null;
  mode: string | null;
  theme: string | null;
  status: RunStatus;
  overall_score: number | null;
}

export interface StartRunResponse {
  run_id: string;
}

export type AgentRole = "html_generator" | "visual_qa";

export type WorkflowNode =
  | "research"
  | "brand"
  | "strategy"
  | "creative"
  | "image_asset"
  | "dialogue"
  | "package";

export type IssueSeverity = "low" | "medium" | "high";

export interface QaIssue {
  severity: IssueSeverity;
  problem: string;
  recommended_fix: string;
  suspected_cause: string;
  regeneration_instruction: string;
}

export interface QaReport {
  approved: boolean;
  overall_score: number;
  visual_quality: number;
  brand_consistency: number;
  readability: number;
  cta_visibility: number;
  responsive_layout: number;
  accessibility: number;
  issues: QaIssue[];
  summary: string;
}

export const WORKFLOW_NODE_ORDER: readonly WorkflowNode[] = [
  "research",
  "brand",
  "strategy",
  "creative",
  "image_asset",
  "dialogue",
  "package",
] as const;

export const DEFAULT_BRIEF: CampaignBrief = {
  url: "https://www.nike.com",
  campaign_type: "Landing hero",
  goal: "Drive holiday gift purchases",
  theme: "Christmas",
  audience: "Holiday shoppers buying athletic gifts",
  tone: "Premium and energetic",
  offer: "Holiday gift edit",
  cta_preference: "Shop Gifts",
};
