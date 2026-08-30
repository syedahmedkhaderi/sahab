"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { AlertCircle, ArrowLeft } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { Wordmark } from "@/components/Wordmark";
import { SessionStateBadge } from "@/components/SessionStateBadge";
import { sessions as sessionsApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { Session } from "@/lib/types";

const TERMINAL_STATES = ["stopped", "failed"] as const;
const READY_STATE = "running";
const POLL_INTERVAL_MS = 3000;
const MAX_POLLS = 60; // ~3 minutes

export default function SessionConnectPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;

  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);
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
      setError(
        e instanceof Error
          ? e.message
          : "Lost contact with the server while waiting."
      );
      return null;
    }
  }, [sessionId, router]);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    // Local counter — the recursive poll closure cannot see the React state
    // value (it would be captured at 0), so the timeout guard uses this.
    let count = 0;

    const poll = async () => {
      if (cancelled) return;
      const s = await fetchSession();
      if (!s || cancelled) return;

      count += 1;

      if (s.state === READY_STATE) {
        setRedirecting(true);
        try {
          const conn = await sessionsApi.connect(s.id);
          if (!cancelled) window.location.href = conn.url;
        } catch {
          if (!cancelled) router.push("/dashboard");
        }
        return;
      }

      if ((TERMINAL_STATES as readonly string[]).includes(s.state)) return;

      if (count >= MAX_POLLS) {
        setError(
          "This is taking longer than it should. Your session may still be starting — check the dashboard in a minute."
        );
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
  const failed = session?.state === "failed";

  return (
    <div className="flex min-h-screen flex-col bg-background px-4 py-10 sm:py-16">
      <div className="mx-auto w-full max-w-form">
        <Link href="/dashboard" className="inline-block rounded-sm">
          <Wordmark />
        </Link>

        <div className="mt-8 rounded-md border border-border bg-card p-6">
          <div className="flex items-start justify-between gap-3">
            <h1 className="text-xl font-semibold tracking-tight text-foreground">
              {redirecting
                ? "Opening your workspace"
                : isQueued
                  ? "Waiting for a GPU"
                  : failed
                    ? "Your workspace did not start"
                    : isTerminal
                      ? "This session has ended"
                      : "Starting your workspace"}
            </h1>
            {session && <SessionStateBadge state={session.state} />}
          </div>

          <div className="mt-5 space-y-4">
            {!isTerminal && !error && (
              <div className="flex items-start gap-2.5 text-sm text-muted-foreground">
                <span className="mt-0.5 flex">
                  <Spinner
                    label={redirecting ? "Opening" : "Starting"}
                    className="text-primary"
                  />
                </span>
                <p>
                  {redirecting ? (
                    "Handing you over to JupyterLab. Your browser will move on its own."
                  ) : isQueued ? (
                    session?.queue_pos != null ? (
                      <>
                        You are number{" "}
                        <span className="font-mono font-medium text-foreground">
                          {session.queue_pos}
                        </span>{" "}
                        in the queue. This page moves you along automatically when
                        a GPU frees up, and you can close it and come back later
                        without losing your place.
                      </>
                    ) : (
                      "Waiting for a GPU to free up. This page will move you along on its own."
                    )
                  ) : session?.state === "starting" ? (
                    "Pulling the environment and starting your container. This usually takes 30 to 60 seconds."
                  ) : (
                    "Sending your request to the scheduler."
                  )}
                </p>
              </div>
            )}

            {isTerminal && (
              <p className="text-sm text-muted-foreground">
                {failed
                  ? "Something went wrong while starting the container. Nothing was charged for it. Try again, and tell the platform team if it keeps happening."
                  : "You can start a new workspace whenever you need one. Your files are still where you left them."}
              </p>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" aria-hidden="true" />
                <AlertTitle>Something went wrong</AlertTitle>
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}

            <div className="flex flex-wrap gap-2">
              <Button variant="outline" size="sm" asChild>
                <Link href="/dashboard">
                  <ArrowLeft className="h-4 w-4" aria-hidden="true" />
                  Dashboard
                </Link>
              </Button>
              {isTerminal && (
                <Button size="sm" asChild>
                  <Link href="/launch">Start another workspace</Link>
                </Button>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
