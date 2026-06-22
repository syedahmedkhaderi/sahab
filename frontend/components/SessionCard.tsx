"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ExternalLink, Square, Clock, Cpu } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { sessions as sessionsApi } from "@/lib/api";
import type { Session } from "@/lib/types";
import { elapsedMinutes, formatDuration } from "@/lib/utils";
import { SessionStateBadge } from "@/components/SessionStateBadge";

interface SessionCardProps {
  session: Session;
  onStopped?: () => void;
}

export function SessionCard({ session, onStopped }: SessionCardProps) {
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isActive = ["starting", "running", "queued"].includes(session.state);
  const isRunning = session.state === "running";
  const isQueued = session.state === "queued";

  const elapsed = session.started_at
    ? elapsedMinutes(session.started_at)
    : null;

  const handleStop = async () => {
    setStopping(true);
    setError(null);
    try {
      await sessionsApi.stop(session.id);
      onStopped?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop session");
      setStopping(false);
    }
  };

  if (!isActive) return null;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Active Session
        </CardTitle>
        <SessionStateBadge state={session.state} />
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {/* Image name */}
          <div>
            <p className="text-base font-semibold">
              {session.image?.name ?? "Workspace"}
            </p>
            <div className="mt-1 flex items-center gap-3 text-sm text-muted-foreground">
              <span className="flex items-center gap-1">
                <Cpu className="h-3.5 w-3.5" />
                {session.resource_type === "l4_gpu" ? "GPU (NVIDIA L4)" : "CPU only"}
              </span>
              {elapsed !== null && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3.5 w-3.5" />
                  {formatDuration(elapsed)} elapsed
                </span>
              )}
            </div>
          </div>

          {/* Queue position */}
          {isQueued && session.queue_pos !== null && (
            <div className="rounded-md bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
              Position {session.queue_pos} in GPU queue — you will be notified when a GPU is available.
            </div>
          )}

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          {/* Actions */}
          <div className="flex items-center gap-2 pt-1">
            {isRunning && session.workspace_url && (
              <Link href={session.workspace_url} target="_blank">
                <Button size="sm" className="flex items-center gap-1.5">
                  <ExternalLink className="h-4 w-4" />
                  Open Workspace
                </Button>
              </Link>
            )}
            {isRunning && !session.workspace_url && (
              <Link href={`/sessions/${session.id}/connect`}>
                <Button size="sm" className="flex items-center gap-1.5">
                  <ExternalLink className="h-4 w-4" />
                  Open Workspace
                </Button>
              </Link>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={handleStop}
              disabled={stopping}
              className="flex items-center gap-1.5 text-destructive hover:text-destructive"
            >
              <Square className="h-4 w-4" />
              {stopping ? "Stopping..." : "Stop Session"}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
