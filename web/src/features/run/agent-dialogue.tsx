import { useEffect, useRef } from "react";
import { Bot, Eye, User } from "lucide-react";

import {
  Avatar,
  AvatarFallback,
} from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";
import { useRunStore } from "@/store/run-store";
import type { AgentBubble } from "@/store/run-store";

export function AgentDialogue() {
  // Subscribe only to the ordered list of bubble ids — not the bubble bodies.
  // This keeps the parent stable even as deltas mutate individual bubbles.
  const transcript = useRunStore((s) => s.transcript);
  const lastSeq = useRunStore((s) => s.lastSeq);
  const scrollRef = useRef<HTMLDivElement | null>(null);

  // Scroll to bottom whenever a new event arrives — covers both transcript
  // additions and delta-driven height growth.
  useEffect(() => {
    const node = scrollRef.current;
    if (!node) return;
    const viewport = node.querySelector<HTMLElement>(
      "[data-radix-scroll-area-viewport]",
    );
    if (!viewport) return;
    viewport.scrollTop = viewport.scrollHeight;
  }, [transcript.length, lastSeq]);

  return (
    <Card className="flex h-full flex-col overflow-hidden">
      <CardHeader className="pb-3">
        <CardTitle className="text-base">Agent dialogue</CardTitle>
        <p className="text-xs text-muted-foreground">
          HTML Generator on the left, Visual QA on the right. Watch them argue
          until QA approves.
        </p>
      </CardHeader>
      <ScrollArea ref={scrollRef} className="flex-1 px-6">
        <CardContent className="flex flex-col gap-4 px-0 pb-6 pt-0">
          {transcript.length === 0 ? (
            <p className="rounded-md border border-dashed bg-muted/30 px-4 py-10 text-center text-sm text-muted-foreground">
              Waiting for the agents to start chatting…
            </p>
          ) : (
            transcript.map((id) => <BubbleSubscriber key={id} bubbleId={id} />)
          )}
        </CardContent>
      </ScrollArea>
    </Card>
  );
}

/**
 * One subscriber per bubble — selecting only the bubble's own data means a
 * delta arriving on bubble A does not re-render bubbles B, C, … on the page.
 * This is the key to smooth typewriter UX without thrashing the transcript.
 */
function BubbleSubscriber({ bubbleId }: { bubbleId: string }) {
  const bubble = useRunStore((s) => s.bubbles[bubbleId as keyof typeof s.bubbles]);
  if (!bubble) return null;
  return <Bubble bubble={bubble} />;
}

function Bubble({ bubble }: { bubble: AgentBubble }) {
  if (bubble.role === "human") {
    return <HumanBubble bubble={bubble} />;
  }
  const isGenerator = bubble.role === "html_generator";
  return (
    <div
      className={cn(
        "flex items-start gap-3",
        isGenerator ? "justify-start" : "justify-end",
      )}
    >
      {isGenerator && <RoleAvatar role="html_generator" />}
      <div
        className={cn(
          "max-w-[80%] rounded-2xl px-4 py-3 text-sm shadow-sm",
          isGenerator
            ? "rounded-tl-sm bg-muted text-foreground"
            : "rounded-tr-sm bg-primary text-primary-foreground",
        )}
      >
        <div
          className={cn(
            "mb-1 flex items-center gap-2 text-xs font-medium",
            isGenerator
              ? "text-muted-foreground"
              : "text-primary-foreground/80",
          )}
        >
          <span>{isGenerator ? "HTML Generator" : "Visual QA"}</span>
          <span
            className={cn(
              "rounded-md px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
              isGenerator
                ? "bg-background/60"
                : "bg-primary-foreground/15 text-primary-foreground",
            )}
          >
            Attempt {bubble.attempt + 1}
          </span>
          {!bubble.finalized && (
            <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wide opacity-70">
              <span className="h-1 w-1 animate-pulse rounded-full bg-current" />
              Streaming
            </span>
          )}
        </div>
        <p className="whitespace-pre-wrap break-words leading-relaxed">
          {bubble.text}
          {!bubble.finalized && (
            <span
              aria-hidden
              className="ml-0.5 inline-block h-3 w-0.5 translate-y-0.5 animate-pulse bg-current opacity-70"
            />
          )}
        </p>
        {bubble.finalized && bubble.questions_for_qa && bubble.questions_for_qa.length > 0 && (
          <BubbleChips
            label="Questions for QA"
            items={bubble.questions_for_qa}
            variant={isGenerator ? "muted" : "primary"}
          />
        )}
        {bubble.finalized && bubble.answers_to_generator && bubble.answers_to_generator.length > 0 && (
          <BubbleChips
            label="Answers to Generator"
            items={bubble.answers_to_generator}
            variant={isGenerator ? "muted" : "primary"}
          />
        )}
        {bubble.finalized && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {bubble.html_provided && (
              <Badge
                variant="secondary"
                className="bg-background/60 text-[10px]"
              >
                Submitted attempt {bubble.attempt + 1}
              </Badge>
            )}
            {!isGenerator && (
              <Badge
                variant="secondary"
                className="bg-primary-foreground/15 text-[10px] text-primary-foreground"
              >
                QA report issued
              </Badge>
            )}
          </div>
        )}
      </div>
      {!isGenerator && <RoleAvatar role="visual_qa" />}
    </div>
  );
}

function BubbleChips({
  label,
  items,
  variant,
}: {
  label: string;
  items: string[];
  variant: "muted" | "primary";
}) {
  return (
    <div className="mt-3">
      <p
        className={cn(
          "mb-1 text-[10px] font-semibold uppercase tracking-wide",
          variant === "muted"
            ? "text-muted-foreground"
            : "text-primary-foreground/70",
        )}
      >
        {label}
      </p>
      <ul className="flex flex-wrap gap-1.5">
        {items.map((item, i) => (
          <li
            key={i}
            className={cn(
              "rounded-full px-2.5 py-0.5 text-xs",
              variant === "muted"
                ? "bg-background/60 text-foreground"
                : "bg-primary-foreground/10 text-primary-foreground",
            )}
          >
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function RoleAvatar({ role }: { role: AgentBubble["role"] }) {
  if (role === "html_generator") {
    return (
      <Avatar className="h-8 w-8 border bg-background">
        <AvatarFallback className="bg-amber-500/15 text-amber-700 dark:text-amber-300">
          <Bot className="h-4 w-4" />
        </AvatarFallback>
      </Avatar>
    );
  }
  if (role === "human") {
    return (
      <Avatar className="h-8 w-8 border bg-background">
        <AvatarFallback className="bg-sky-500/15 text-sky-700 dark:text-sky-300">
          <User className="h-4 w-4" />
        </AvatarFallback>
      </Avatar>
    );
  }
  return (
    <Avatar className="h-8 w-8 border bg-background">
      <AvatarFallback className="bg-violet-500/15 text-violet-700 dark:text-violet-300">
        <Eye className="h-4 w-4" />
      </AvatarFallback>
    </Avatar>
  );
}

function HumanBubble({ bubble }: { bubble: AgentBubble }) {
  return (
    <div className="flex w-full justify-center">
      <div className="flex max-w-[90%] items-start gap-3 rounded-xl border border-sky-500/30 bg-sky-500/5 px-4 py-3 text-sm shadow-sm">
        <RoleAvatar role="human" />
        <div className="min-w-0 flex-1">
          <div className="mb-1 flex items-center gap-2 text-xs font-medium text-sky-700 dark:text-sky-300">
            <span>Director (you)</span>
            <span className="rounded-md bg-sky-500/15 px-1.5 py-0.5 text-[10px] uppercase tracking-wide">
              Feedback
            </span>
          </div>
          <p className="whitespace-pre-wrap break-words leading-relaxed">
            {bubble.text}
          </p>
        </div>
      </div>
    </div>
  );
}
