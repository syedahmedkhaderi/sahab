import React from "react";
import { Badge } from "@/components/ui/badge";
import type { SessionState } from "@/lib/types";

interface SessionStateBadgeProps {
  state: SessionState;
}

export function SessionStateBadge({ state }: SessionStateBadgeProps) {
  switch (state) {
    case "running":
      return <Badge variant="success">Running</Badge>;
    case "starting":
      return <Badge variant="secondary">Starting</Badge>;
    case "queued":
      return <Badge variant="warning">Queued</Badge>;
    case "stopping":
      return <Badge variant="secondary">Stopping</Badge>;
    case "stopped":
      return <Badge variant="outline">Stopped</Badge>;
    case "failed":
      return <Badge variant="destructive">Failed</Badge>;
    case "requested":
      return <Badge variant="secondary">Requested</Badge>;
    default:
      return <Badge variant="outline">{state}</Badge>;
  }
}
