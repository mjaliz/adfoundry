import { create } from "zustand";

import type {
  AgentRole,
  CampaignBrief,
  QaReport,
  RunMode,
  RunStatus,
  WorkflowNode,
} from "@/types/api";
import type {
  NodeCompletedData,
  RunEvent,
} from "@/types/events";

/**
 * Bubble identity = (role, attempt). The pair is unique per dialogue turn.
 * We keep order in `transcript` for stable rendering, and text+meta in
 * `bubbles` keyed by that id so per-bubble subscriptions only re-render the
 * one bubble whose text changed (typewriter UX without transcript thrashing).
 */
export type BubbleId = `${AgentRole}-${number}`;

export interface AgentBubble {
  id: BubbleId;
  role: AgentRole;
  attempt: number;
  text: string;
  /** Whether the agent_message_completed event has finalized this bubble. */
  finalized: boolean;
  /** Set on completion when present in payload. */
  questions_for_qa?: string[];
  answers_to_generator?: string[];
  rationale?: string;
  html_provided?: boolean;
}

export interface NodeState {
  status: "idle" | "running" | "done";
  summary: string;
  data?: NodeCompletedData;
}

export interface NodeProgress {
  text: string;
  kind: "delta" | "status";
}

export interface RenderArtifacts {
  attempt: number;
  htmlPath: string;
  desktopScreenshot: string;
  mobileScreenshot: string;
  /** Bumps every render to force the iframe to refresh. */
  refreshKey: number;
}

export interface QaSnapshot {
  attempt: number;
  report: QaReport;
}

export interface RunState {
  runId: string | null;
  status: RunStatus;
  mode: RunMode | null;
  brief: CampaignBrief | null;
  startedAt: string | null;
  completedAt: string | null;
  errorMessage: string | null;
  approved: boolean | null;
  overallScore: number | null;
  /** Total events seen — used for guarding against duplicate appends. */
  lastSeq: number;
  nodes: Record<WorkflowNode, NodeState>;
  /** Live streaming/status text per node — populated while a node is running. */
  nodeProgress: Record<WorkflowNode, NodeProgress | null>;
  /** Ordered list of bubble ids — drives transcript layout. */
  transcript: BubbleId[];
  /** Per-bubble payload. Mutated as deltas arrive. */
  bubbles: Record<BubbleId, AgentBubble>;
  render: RenderArtifacts | null;
  qa: QaSnapshot | null;
  /** Counter of html_render_completed events — drives iframe key. */
  renderRefreshCounter: number;
}

const EMPTY_NODE: NodeState = { status: "idle", summary: "" };

const INITIAL_NODES: Record<WorkflowNode, NodeState> = {
  research: { ...EMPTY_NODE },
  brand: { ...EMPTY_NODE },
  strategy: { ...EMPTY_NODE },
  creative: { ...EMPTY_NODE },
  image_asset: { ...EMPTY_NODE },
  dialogue: { ...EMPTY_NODE },
  package: { ...EMPTY_NODE },
};

const INITIAL_NODE_PROGRESS: Record<WorkflowNode, NodeProgress | null> = {
  research: null,
  brand: null,
  strategy: null,
  creative: null,
  image_asset: null,
  dialogue: null,
  package: null,
};

export const INITIAL_RUN_STATE: RunState = {
  runId: null,
  status: "unknown",
  mode: null,
  brief: null,
  startedAt: null,
  completedAt: null,
  errorMessage: null,
  approved: null,
  overallScore: null,
  lastSeq: 0,
  nodes: INITIAL_NODES,
  nodeProgress: INITIAL_NODE_PROGRESS,
  transcript: [],
  bubbles: {},
  render: null,
  qa: null,
  renderRefreshCounter: 0,
};

interface RunStoreActions {
  reset: (runId: string) => void;
  apply: (event: RunEvent) => void;
}

export type RunStore = RunState & RunStoreActions;

function summarizeNode(data: NodeCompletedData): string {
  switch (data.node) {
    case "research":
      return data.title ? `${data.title}` : data.final_url ?? "Research complete";
    case "brand":
      return [data.brand_name, data.tone_of_voice].filter(Boolean).join(" — ");
    case "strategy":
      return data.selected_angle ?? data.selected_name ?? "Strategy chosen";
    case "creative":
      return data.headline ?? data.concept_name ?? "Creative drafted";
    case "image_asset":
      return data.generation_mode
        ? `Hero (${data.generation_mode})`
        : "Hero asset ready";
    case "dialogue":
      return typeof data.overall_score === "number"
        ? `${data.approved ? "Approved" : "Closed"} · score ${data.overall_score}`
        : "Dialogue complete";
    case "package":
      return "Package written";
    default:
      return "";
  }
}

function bubbleId(role: AgentRole, attempt: number): BubbleId {
  return `${role}-${attempt}` as BubbleId;
}

function reducer(state: RunState, event: RunEvent): RunState {
  // Guard against duplicate replays by seq, but allow seq=0 (defensive).
  if (event.seq <= state.lastSeq) {
    return state;
  }
  const next: RunState = { ...state, lastSeq: event.seq };

  switch (event.type) {
    case "run_started": {
      next.runId = event.data.run_id;
      next.mode = event.data.mode;
      next.brief = event.data.brief;
      next.startedAt = event.timestamp;
      next.status = "running";
      next.errorMessage = null;
      return next;
    }
    case "run_completed": {
      next.status = "completed";
      next.completedAt = event.timestamp;
      next.approved = event.data.approved;
      next.overallScore = event.data.overall_score;
      return next;
    }
    case "run_failed": {
      next.status = "failed";
      next.completedAt = event.timestamp;
      next.errorMessage = event.data.error;
      return next;
    }
    case "node_started": {
      next.nodes = {
        ...state.nodes,
        [event.data.node]: { status: "running", summary: "" },
      };
      next.nodeProgress = {
        ...state.nodeProgress,
        [event.data.node]: null,
      };
      return next;
    }
    case "node_completed": {
      next.nodes = {
        ...state.nodes,
        [event.data.node]: {
          status: "done",
          summary: summarizeNode(event.data),
          data: event.data,
        },
      };
      next.nodeProgress = {
        ...state.nodeProgress,
        [event.data.node]: null,
      };
      return next;
    }
    case "node_progress": {
      const { node, text, kind } = event.data;
      const existing = state.nodeProgress[node];
      const merged: NodeProgress =
        kind === "delta"
          ? {
              kind: "delta",
              text: (existing?.kind === "delta" ? existing.text : "") + text,
            }
          : { kind: "status", text };
      next.nodeProgress = { ...state.nodeProgress, [node]: merged };
      return next;
    }
    case "agent_message_started": {
      const id = bubbleId(event.data.role, event.data.attempt);
      if (state.bubbles[id]) {
        // Re-open (e.g. retry of same attempt) — clear text.
        next.bubbles = {
          ...state.bubbles,
          [id]: { ...state.bubbles[id], text: "", finalized: false },
        };
        return next;
      }
      next.bubbles = {
        ...state.bubbles,
        [id]: {
          id,
          role: event.data.role,
          attempt: event.data.attempt,
          text: "",
          finalized: false,
        },
      };
      next.transcript = [...state.transcript, id];
      return next;
    }
    case "agent_message_delta": {
      const id = bubbleId(event.data.role, event.data.attempt);
      const existing = state.bubbles[id];
      if (!existing) {
        // No "started" seen — synthesize a new bubble defensively.
        const fresh: AgentBubble = {
          id,
          role: event.data.role,
          attempt: event.data.attempt,
          text: event.data.text,
          finalized: false,
        };
        next.bubbles = { ...state.bubbles, [id]: fresh };
        next.transcript = [...state.transcript, id];
        return next;
      }
      next.bubbles = {
        ...state.bubbles,
        [id]: { ...existing, text: existing.text + event.data.text },
      };
      return next;
    }
    case "agent_message_completed": {
      const id = bubbleId(event.data.role, event.data.attempt);
      const existing = state.bubbles[id];
      const finalText = event.data.chat_message;
      const merged: AgentBubble = {
        id,
        role: event.data.role,
        attempt: event.data.attempt,
        // Prefer the canonical chat_message (handles non-streaming runs that
        // emit only completed events without deltas).
        text:
          existing && existing.text.length > finalText.length
            ? existing.text
            : finalText,
        finalized: true,
        html_provided: event.data.html_provided,
        questions_for_qa: event.data.questions_for_qa,
        answers_to_generator: event.data.answers_to_generator,
        rationale: event.data.rationale,
      };
      next.bubbles = { ...state.bubbles, [id]: merged };
      if (!state.transcript.includes(id)) {
        next.transcript = [...state.transcript, id];
      }
      return next;
    }
    case "html_render_started": {
      // Mark dialogue node as running for visual cue.
      if (state.nodes.dialogue.status === "idle") {
        next.nodes = {
          ...state.nodes,
          dialogue: { status: "running", summary: "" },
        };
      }
      return next;
    }
    case "html_render_completed": {
      next.render = {
        attempt: event.data.attempt,
        htmlPath: event.data.html_path,
        desktopScreenshot: event.data.desktop_screenshot,
        mobileScreenshot: event.data.mobile_screenshot,
        refreshKey: state.renderRefreshCounter + 1,
      };
      next.renderRefreshCounter = state.renderRefreshCounter + 1;
      return next;
    }
    case "qa_report_completed": {
      next.qa = { attempt: event.data.attempt, report: event.data.report };
      return next;
    }
    case "dialogue_turn_completed": {
      // Cumulative score reflects latest QA — already captured by qa state.
      return next;
    }
    default: {
      // Exhaustiveness guard: TS will error if a new event type is added.
      const _exhaustive: never = event;
      void _exhaustive;
      return state;
    }
  }
}

export const useRunStore = create<RunStore>((set) => ({
  ...INITIAL_RUN_STATE,
  reset: (runId: string) =>
    set(() => ({ ...INITIAL_RUN_STATE, runId })),
  apply: (event: RunEvent) =>
    set((state) => reducer(state, event)),
}));
