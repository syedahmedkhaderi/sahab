"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { ExternalLink, Server, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { EmptyState } from "@/components/ui/empty-state";
import { Spinner } from "@/components/ui/spinner";
import { SiteHeader } from "@/components/SiteHeader";
import { Wordmark } from "@/components/Wordmark";
import { sessions as sessionsApi, rates as ratesApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { Session, Rate } from "@/lib/types";
import { creditsWithUnit, elapsedMinutes, formatDuration } from "@/lib/utils";

/** States in which the workspace frame should still be on screen. */
const LIVE_STATES = ["running", "stopping"];

const POLL_MS = 10_000;
// formatDuration has one-minute granularity, so a one-second tick would
// re-render the header thirty times to show the same string.
const TICK_MS = 30_000;
// The first load runs the OAuth redirect chain. If nothing has painted by
// then, something is wrong and the user needs a way out.
const LOAD_TIMEOUT_MS = 25_000;

/**
 * The workspace frame, isolated so it cannot remount.
 *
 * The header around it re-renders on every tick. If this element's props or
 * position in the tree changed, React would tear down the iframe and the user
 * would lose their open notebooks, their kernel, and their place, then sit
 * through the OAuth handoff again. Memoising on `src` alone makes that
 * structural rather than a promise.
 */
const WorkspaceFrame = React.memo(function WorkspaceFrame({
  src,
  onLoad,
}: {
  src: string;
  onLoad: () => void;
}) {
  return (
    <iframe
      src={src}
      onLoad={onLoad}
      title="JupyterLab workspace"
      className="absolute inset-0 h-full w-full border-0"
      allow="clipboard-read; clipboard-write"
    />
  );
});

export default function WorkspacePage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const sessionId = params.id;

  const [session, setSession] = useState<Session | null>(null);
  const [frameSrc, setFrameSrc] = useState<string | null>(null);
  const [ratePerMinute, setRatePerMinute] = useState<number | null>(null);
  const [stopping, setStopping] = useState(false);
  const [stopError, setStopError] = useState<string | null>(null);
  const [frameStalled, setFrameStalled] = useState(false);
  const [, setNow] = useState(Date.now());

  const hasLoadedOnce = useRef(false);

  const fetchSession = useCallback(async () => {
    try {
      return await sessionsApi.get(sessionId);
    } catch (e) {
      if (e instanceof ApiClientError && e.status === 401) {
        router.replace("/login");
      }
      return null;
    }
  }, [sessionId, router]);

  // Open once: confirm the session is running, then resolve the workspace URL.
  useEffect(() => {
    let cancelled = false;

    (async () => {
      const s = await fetchSession();
      if (!s || cancelled) return;
      setSession(s);

      if (!LIVE_STATES.includes(s.state)) {
        // The connect page owns the waiting and failure UX; do not duplicate it.
        if (s.state !== "stopped" && s.state !== "failed") {
          router.replace(`/sessions/${sessionId}/connect`);
        }
        return;
      }

      try {
        const conn = await sessionsApi.connect(s.id);
        if (!cancelled) setFrameSrc(conn.url);
      } catch (e) {
        // A 401 here means the Sahab cookie is already gone. Bounce the TOP
        // window now: letting the iframe discover it would render the API's
        // raw 401 JSON inside the frame, with no URL bar and no way out.
        if (e instanceof ApiClientError && e.status === 401) {
          router.replace(
            `/login?from=${encodeURIComponent(`/sessions/${sessionId}/workspace`)}`
          );
        } else if (!cancelled) {
          setFrameStalled(true);
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [fetchSession, router, sessionId]);

  // The rate does not change minute to minute, so it is fetched once.
  useEffect(() => {
    ratesApi
      .list()
      .then((rs: Rate[]) => {
        const match = rs.find((r) => r.resource_type === session?.resource_type);
        if (match) setRatePerMinute(match.credits_per_minute);
      })
      .catch(() => {
        // Elapsed time still reads correctly without it; the credit estimate
        // is simply omitted rather than shown as zero.
      });
  }, [session?.resource_type]);

  // Watch for the session ending underneath us, and keep the clock moving.
  useEffect(() => {
    if (!session || !LIVE_STATES.includes(session.state)) return;

    const poll = setInterval(async () => {
      const s = await fetchSession();
      if (s) setSession(s);
    }, POLL_MS);
    const tick = setInterval(() => setNow(Date.now()), TICK_MS);

    return () => {
      clearInterval(poll);
      clearInterval(tick);
    };
  }, [session, fetchSession]);

  // Arm the stall timer for the first paint only. onLoad fires again on every
  // intermediate redirect in the OAuth chain.
  useEffect(() => {
    if (!frameSrc || hasLoadedOnce.current) return;
    const timer = setTimeout(() => {
      if (!hasLoadedOnce.current) setFrameStalled(true);
    }, LOAD_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [frameSrc]);

  const handleFrameLoad = useCallback(() => {
    hasLoadedOnce.current = true;
    setFrameStalled(false);
  }, []);

  const handleStop = async () => {
    // Stopping deletes the workspace's files. That is a one-way door, and the
    // button sits next to a notebook someone has been working in all afternoon,
    // so it asks rather than assumes.
    if (
      !window.confirm(
        "Stop this workspace?\n\nEverything saved inside it is deleted when it " +
          "stops. Download anything you want to keep first."
      )
    ) {
      return;
    }
    setStopping(true);
    setStopError(null);
    try {
      await sessionsApi.stop(sessionId);
      router.replace("/dashboard");
    } catch (e) {
      setStopError(
        e instanceof Error ? e.message : "Could not stop the workspace."
      );
      setStopping(false);
    }
  };

  const isGpu = session?.resource_type === "l4_gpu";
  const elapsed = session?.started_at ? elapsedMinutes(session.started_at) : null;
  const creditsUsed =
    elapsed !== null && ratePerMinute !== null && ratePerMinute > 0
      ? elapsed * ratePerMinute
      : null;
  const ended = session != null && !LIVE_STATES.includes(session.state);

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <SiteHeader fullBleed>
        <div className="flex min-w-0 items-center gap-4">
          <Link href="/dashboard" className="shrink-0 rounded-sm">
            <Wordmark />
          </Link>

          {session && (
            <div className="hidden min-w-0 items-center gap-3 sm:flex">
              <span className="shrink-0 font-mono text-sm text-muted-foreground">
                {isGpu ? "NVIDIA L4" : "CPU only"}
              </span>
              {session.image_name && (
                <span className="hidden truncate text-sm text-muted-foreground lg:inline">
                  {session.image_name}
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {session && !ended && (
            <div className="hidden items-baseline gap-3 md:flex">
              {elapsed !== null && (
                <span className="font-mono text-sm text-muted-foreground">
                  {formatDuration(elapsed)}
                </span>
              )}
              {creditsUsed !== null && (
                // "About": the backend meter is authoritative. This is a
                // client-side estimate and must not read like a balance.
                <span className="hidden font-mono text-sm text-muted-foreground lg:inline">
                  about {creditsWithUnit(creditsUsed)}
                </span>
              )}
            </div>
          )}

          {frameSrc && !ended && (
            <Button variant="ghost" size="sm" asChild>
              <a href={frameSrc} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4" aria-hidden="true" />
                <span className="hidden sm:inline">Open in new tab</span>
              </a>
            </Button>
          )}

          {!ended && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleStop}
              loading={stopping}
              className="text-destructive hover:bg-destructive-subtle hover:text-destructive-strong"
            >
              {!stopping && <Square className="h-3.5 w-3.5" aria-hidden="true" />}
              {stopping ? "Stopping" : "Stop workspace"}
            </Button>
          )}
        </div>
      </SiteHeader>

      {/* Files die with the session, so the warning has to be in front of the
          person while they work — not buried in docs they will read afterwards,
          if ever. Kept to one quiet line so it does not compete with the
          notebook itself. */}
      {session && !ended && (
        <p
          className="shrink-0 border-b border-border bg-warning-subtle px-4 py-1.5 text-center text-xs text-warning-strong"
          role="status"
        >
          Files in this workspace are deleted when it stops. Download anything
          you want to keep.
        </p>
      )}

      <div className="relative flex-1">
        {ended ? (
          <div className="mx-auto max-w-prose p-6">
            <EmptyState
              icon={Server}
              title={
                session?.state === "failed"
                  ? "This workspace did not start"
                  : "This workspace has stopped"
              }
              description={
                session?.state === "failed"
                  ? "Nothing was charged for it. You can try again, and tell the platform team if it keeps happening."
                  : "The GPU is back in the pool, and this workspace's files have been deleted. Anything you downloaded is still on your computer."
              }
              action={
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" asChild>
                    <Link href="/launch">Start another workspace</Link>
                  </Button>
                  <Button variant="outline" size="sm" asChild>
                    <Link href="/dashboard">Dashboard</Link>
                  </Button>
                </div>
              }
            />
          </div>
        ) : frameSrc ? (
          <>
            <WorkspaceFrame src={frameSrc} onLoad={handleFrameLoad} />
            {frameStalled && (
              <div className="absolute inset-x-0 top-0 p-4">
                <Alert variant="warning" className="mx-auto max-w-prose shadow-popover">
                  <AlertTitle>The workspace is slow to appear</AlertTitle>
                  <AlertDescription className="mt-1.5 space-y-3">
                    <p>
                      Your session is running, but JupyterLab has not loaded in this
                      frame yet. Opening it in its own tab usually works.
                    </p>
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" asChild>
                        <a href={frameSrc} target="_blank" rel="noopener noreferrer">
                          Open in a new tab
                        </a>
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        onClick={() => window.location.reload()}
                      >
                        Reload
                      </Button>
                    </div>
                  </AlertDescription>
                </Alert>
              </div>
            )}
          </>
        ) : (
          <div className="flex h-full items-center justify-center gap-2.5 text-sm text-muted-foreground">
            <Spinner label="Opening your workspace" className="text-primary" />
            Opening your workspace
          </div>
        )}
      </div>

      {stopError && (
        <div className="border-t border-border p-4">
          <Alert variant="destructive" className="mx-auto max-w-prose">
            <AlertDescription>{stopError}</AlertDescription>
          </Alert>
        </div>
      )}
    </div>
  );
}
