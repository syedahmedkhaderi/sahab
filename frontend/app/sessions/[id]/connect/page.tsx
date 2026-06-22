"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { Loader2, ExternalLink, AlertCircle, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { SessionStateBadge } from "@/components/SessionStateBadge";
import { sessions as sessionsApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { Session } from "@/lib/types";

const TERMINAL_STATES = ["stopped", "failed"] as const;
const READY_STATE = "running";
const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 60; // 3 min timeout

export default function SessionConnectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;

  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [polls, setPolls] = useState(0);
  const [redirecting, setRedirecting] = useState(false);

  const fetchSession = useCallback(async () => {
    try {
      const s = await sessionsApi.get(sessionId);
      setSession(s);
      return s;
    } catch (e) {
      if (e instanceof ApiClientError && e.status === 401) {
        router.replace("/login");
      }
      setError(e instanceof Error ? e.message : "Failed to fetch session.");
      return null;
    }
  }, [sessionId, router]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    const poll = async () => {
      if (cancelled) return;
      const s = await fetchSession();
      if (!s || cancelled) return;

      setPolls((p) => p + 1);

      if (s.state === READY_STATE) {
        // Try to get workspace URL
        setRedirecting(true);
        try {
          const conn = await sessionsApi.connect(s.id);
          if (!cancelled) {
            window.location.href = conn.url;
          }
        } catch {
          // connect endpoint failed — fall back to dashboard
          if (!cancelled) router.push("/dashboard");
        }
        return;
      }

      if ((TERMINAL_STATES as readonly string[]).includes(s.state)) {
        return; // stop polling
      }

      if (polls >= MAX_POLLS) {
        setError("Session is taking too long to start. Please check the dashboard.");
        return;
      }

      timer = setTimeout(poll, POLL_INTERVAL_MS);
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [fetchSession]); // eslint-disable-line react-hooks/exhaustive-deps

  const isTerminal =
    session && (TERMINAL_STATES as readonly string[]).includes(session.state);
  const isQueued = session?.state === "queued";

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <div className="w-full max-w-md space-y-4">
        <Card>
          <CardContent className="pt-6">
            <div className="flex flex-col items-center gap-4 text-center">
              {/* Status badge */}
              {session && (
                <div className="flex flex-col items-center gap-2">
                  <SessionStateBadge state={session.state} />
                </div>
              )}

              {/* Spinner / redirecting */}
              {!isTerminal && !error && (
                <>
                  {redirecting ? (
                    <>
                      <Loader2 className="h-10 w-10 animate-spin text-primary" />
                      <h2 className="text-xl font-semibold">Opening workspace...</h2>
                      <p className="text-muted-foreground">
                        Redirecting you to the IDE. This may take a moment.
                      </p>
                    </>
                  ) : isQueued ? (
                    <>
                      <Loader2 className="h-10 w-10 animate-spin text-yellow-500" />
                      <h2 className="text-xl font-semibold">Waiting in queue</h2>
                      <p className="text-muted-foreground">
                        {session?.queue_pos !== null && session?.queue_pos !== undefined
                          ? `You are position ${session.queue_pos} in the GPU queue.`
                          : "Waiting for a GPU to become available."}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        You will be redirected automatically when your session starts.
                      </p>
                    </>
                  ) : (
                    <>
                      <Loader2 className="h-10 w-10 animate-spin text-primary" />
                      <h2 className="text-xl font-semibold">Starting your workspace</h2>
                      <p className="text-muted-foreground">
                        {session?.state === "starting"
                          ? "Container is starting. This takes about 30-60 seconds."
                          : "Processing your request..."}
                      </p>
                    </>
                  )}
                </>
              )}

              {/* Terminal state */}
              {isTerminal && (
                <>
                  <AlertCircle className="h-10 w-10 text-muted-foreground" />
                  <h2 className="text-xl font-semibold">
                    Session {session?.state}
                  </h2>
                  <p className="text-muted-foreground">
                    {session?.state === "failed"
                      ? "The workspace failed to start. Please try launching again."
                      : "This session has ended."}
                  </p>
                </>
              )}

              {/* Error */}
              {error && (
                <Alert variant="destructive" className="text-left">
                  <AlertCircle className="h-4 w-4" />
                  <AlertTitle>Error</AlertTitle>
                  <AlertDescription>{error}</AlertDescription>
                </Alert>
              )}

              {/* Actions */}
              <div className="flex gap-2">
                <Link href="/dashboard">
                  <Button variant="outline" size="sm" className="flex items-center gap-1.5">
                    <ArrowLeft className="h-4 w-4" />
                    Dashboard
                  </Button>
                </Link>
                {session?.state === READY_STATE && session.workspace_url && (
                  <a href={session.workspace_url} target="_blank" rel="noopener noreferrer">
                    <Button size="sm" className="flex items-center gap-1.5">
                      <ExternalLink className="h-4 w-4" />
                      Open Workspace
                    </Button>
                  </a>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
