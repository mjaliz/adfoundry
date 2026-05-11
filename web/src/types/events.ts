// Discriminated union of run events streamed from /api/runs/:id/events.
// Keep in sync with adfoundry/events.py EventType.

import type {
  AgentRole,
  CampaignBrief,
  QaReport,
  RunMode,
  WorkflowNode,
} from "./api";

interface BaseEvent<TType extends string, TData> {
  run_id: string;
  seq: number;
  timestamp: string;
  type: TType;
  data: TData;
}

export interface RunStartedData {
  run_id: string;
  mode: RunMode;
  brief: CampaignBrief;
  output_dir: string;
}

export interface RunCompletedData {
  run_id: string;
  output_dir: string;
  approved: boolean;
  overall_score: number;
}

export interface RunFailedData {
  run_id: string;
  error: string;
  exception_type: string;
}

export interface NodeStartedData {
  node: WorkflowNode;
}

// node_completed has node-specific extras; we keep it loose plus typed accessors.
export interface NodeCompletedData {
  node: WorkflowNode;
  // research
  final_url?: string;
  title?: string;
  source?: string;
  desktop_screenshot?: string;
  mobile_screenshot?: string;
  color_candidates?: string[];
  image_count?: number;
  // brand
  brand_name?: string;
  industry?: string;
  primary_colors?: string[];
  tone_of_voice?: string;
  // strategy
  selected_angle?: string;
  selected_name?: string;
  options_count?: number;
  decisions_count?: number;
  // creative
  concept_name?: string;
  headline?: string;
  subheadline?: string;
  cta?: string;
  // image_asset
  generation_mode?: string;
  hero_image_path?: string;
  reference_count?: number;
  fallback_reason?: string;
  // dialogue
  approved?: boolean;
  overall_score?: number;
  attempts?: number;
  messages?: number;
  // package
  package_path?: string;
  preview_html_path?: string;
}

export interface AgentMessageStartedData {
  role: AgentRole;
  attempt: number;
}

export interface AgentMessageDeltaData {
  role: AgentRole;
  attempt: number;
  text: string;
}

export interface AgentMessageCompletedData {
  role: AgentRole;
  attempt: number;
  chat_message: string;
  html_provided?: boolean;
  questions_for_qa?: string[];
  rationale?: string;
  answers_to_generator?: string[];
}

export interface HtmlRenderStartedData {
  attempt: number;
}

export interface HtmlRenderCompletedData {
  attempt: number;
  html_path: string;
  desktop_screenshot: string;
  mobile_screenshot: string;
  error?: string | null;
}

export interface QaReportCompletedData {
  attempt: number;
  report: QaReport;
}

export interface DialogueTurnCompletedData {
  attempt: number;
  approved: boolean;
  overall_score: number;
  issue_count: number;
}

export type RunEvent =
  | BaseEvent<"run_started", RunStartedData>
  | BaseEvent<"run_completed", RunCompletedData>
  | BaseEvent<"run_failed", RunFailedData>
  | BaseEvent<"node_started", NodeStartedData>
  | BaseEvent<"node_completed", NodeCompletedData>
  | BaseEvent<"agent_message_started", AgentMessageStartedData>
  | BaseEvent<"agent_message_delta", AgentMessageDeltaData>
  | BaseEvent<"agent_message_completed", AgentMessageCompletedData>
  | BaseEvent<"html_render_started", HtmlRenderStartedData>
  | BaseEvent<"html_render_completed", HtmlRenderCompletedData>
  | BaseEvent<"qa_report_completed", QaReportCompletedData>
  | BaseEvent<"dialogue_turn_completed", DialogueTurnCompletedData>;

export type RunEventType = RunEvent["type"];

export const RUN_EVENT_TYPES: readonly RunEventType[] = [
  "run_started",
  "run_completed",
  "run_failed",
  "node_started",
  "node_completed",
  "agent_message_started",
  "agent_message_delta",
  "agent_message_completed",
  "html_render_started",
  "html_render_completed",
  "qa_report_completed",
  "dialogue_turn_completed",
] as const;
