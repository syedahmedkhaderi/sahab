import React from "react";
import { Badge } from "@/components/ui/badge";
import type { SessionState } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * One vocabulary for session state, used everywhere a session appears. The dot
 * carries the state as well as the colour, so the meaning survives a monochrome
 * screen or a reader who cannot separate the two greens.
 */
const STATES: Record<
  SessionState | "default",
  { label: string; variant: "success" | "warning" | "danger" | "info" | "outline"; dot: string }
> = {
  running: { label: "Running", variant: "success", dot: "bg-success" },
  starting: { label: "Starting", variant: "info", dot: "bg-info animate-pulse" },
  requested: { label: "Requested", variant: "info", dot: "bg-info animate-pulse" },
  queued: { label: "Queued", variant: "warning", dot: "bg-warning" },
  stopping: { label: "Stopping", variant: "info", dot: "bg-info animate-pulse" },
  stopped: { label: "Stopped", variant: "outline", dot: "bg-muted-foreground/50" },
  failed: { label: "Failed", variant: "danger", dot: "bg-destructive" },
  default: { label: "Unknown", variant: "outline", dot: "bg-muted-foreground/50" },
};

export function SessionStateBadge({ state }: { state: SessionState }) {
  const config = STATES[state] ?? { ...STATES.default, label: state };
  return (
    <Badge variant={config.variant}>
      <span
        aria-hidden="true"
        className={cn("h-1.5 w-1.5 shrink-0 rounded-full", config.dot)}
      />
      {config.label}
    </Badge>
  );
}
