"use client";

import React, { useState } from "react";
import Link from "next/link";
import { ExternalLink, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { sessions as sessionsApi } from "@/lib/api";
import type { Session } from "@/lib/types";
import { elapsedMinutes, formatDuration } from "@/lib/utils";
import { SessionStateBadge } from "@/components/SessionStateBadge";

interface SessionCardProps {
  session: Session;
  onStopped?: () => void;
}

/**
 * The one workspace a user has running. This is the panel someone looks at
 * while they wait, so each state says what is happening and what to do, rather
 * than only naming itself.
 */
export function SessionCard({ session, onStopped }: SessionCardProps) {
  const [stopping, setStopping] = useState(false);
  const { toast } = useToast();

  const isActive = ["requested", "starting", "running", "queued", "stopping"].includes(
    session.state
  );
  const isRunning = session.state === "running";
  const isQueued = session.state === "queued";
  const isGpu = session.resource_type === "l4_gpu";

  const elapsed = session.started_at ? elapsedMinutes(session.started_at) : null;

  const handleStop = async () => {
    setStopping(true);
    try {
      await sessionsApi.stop(session.id);
      toast({
        tone: "success",
        title: "Workspace stopped",
        description: isGpu ? "The GPU is back in the pool." : undefined,
      });
      onStopped?.();
    } catch (e) {
      toast({
        tone: "error",
        title: "Could not stop the workspace",
        description: e instanceof Error ? e.message : "Please try again.",
      });
      setStopping(false);
    }
  };

  if (!isActive) return null;

  return (
    <section className="rounded-md border border-border bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <h2 className="text-sm font-medium text-foreground">Your workspace</h2>
        <SessionStateBadge state={session.state} />
      </div>

      <div className="space-y-4 p-5">
        <div>
          <p className="text-base font-medium text-foreground">
            {session.image_name ?? "Workspace"}
          </p>
          <p className="mt-1 font-mono text-sm text-muted-foreground">
            {isGpu ? "NVIDIA L4" : "CPU only"}
            {elapsed !== null && ` · ${formatDuration(elapsed)} elapsed`}
          </p>
        </div>

        {session.state === "starting" && (
          <p className="text-sm text-muted-foreground">
            Pulling the environment and starting your container. This usually
            takes under a minute.
          </p>
        )}

        {isQueued && (
          <div className="rounded-md border border-warning/30 bg-warning-subtle px-3.5 py-2.5 text-sm text-warning-strong">
            {session.queue_pos !== null && session.queue_pos !== undefined ? (
              <>
                You are number{" "}
                <span className="font-mono font-medium">{session.queue_pos}</span>{" "}
                in the queue. Your workspace starts on its own as soon as a GPU
                frees up. Leave this page open or come back later.
              </>
            ) : (
              <>
                Waiting for a GPU. Your workspace starts on its own as soon as one
                frees up.
              </>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2">
          {isRunning && (
            <Button size="sm" asChild>
              {/* Straight to the workspace shell: a running session has no
                  waiting to do, so the connect page would only flash past. */}
              <Link href={`/sessions/${session.id}/workspace`}>
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                Open workspace
              </Link>
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            onClick={handleStop}
            loading={stopping}
            className="text-destructive hover:bg-destructive-subtle hover:text-destructive-strong"
          >
            {!stopping && <Square className="h-3.5 w-3.5" aria-hidden="true" />}
            {stopping ? "Stopping" : isQueued ? "Leave the queue" : "Stop workspace"}
          </Button>
        </div>
      </div>
    </section>
  );
}
