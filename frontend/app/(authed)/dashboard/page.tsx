"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus, Server } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { BalanceCard } from "@/components/BalanceCard";
import { SessionCard } from "@/components/SessionCard";
import { SessionStateBadge } from "@/components/SessionStateBadge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { me, sessions as sessionsApi, rates as ratesApi } from "@/lib/api";
import type { User, Session, Rate } from "@/lib/types";
import { formatDateTime, elapsedMinutes, formatDuration } from "@/lib/utils";

const ACTIVE_STATES = ["requested", "queued", "starting", "running", "stopping"];

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null);
  const [sessionList, setSessionList] = useState<Session[]>([]);
  const [gpuRate, setGpuRate] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchData = useCallback(async () => {
    try {
      const [u, s] = await Promise.all([me.get(), sessionsApi.list()]);
      setUser(u);
      setSessionList(s);
    } catch {
      // AuthedLayout handles session expiry redirects
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // The GPU rate does not change minute to minute, so it is fetched once
    // rather than on every poll.
    ratesApi
      .list()
      .then((rates: Rate[]) => {
        const gpu = rates.find((r) => r.resource_type === "l4_gpu");
        if (gpu) setGpuRate(gpu.credits_per_minute);
      })
      .catch(() => {
        // The balance still reads correctly without it; it just cannot say how
        // many hours that is.
      });
  }, [fetchData]);

  useEffect(() => {
    const interval = setInterval(fetchData, 10_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const activeSession = sessionList.find((s) => ACTIVE_STATES.includes(s.state));
  const recentSessions = sessionList
    .filter((s) => s.state === "stopped" || s.state === "failed")
    .slice(0, 8);

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-8 w-40" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
        <Skeleton className="h-48" />
      </div>
    );
  }

  const firstName = user?.full_name?.trim().split(/\s+/)[0];

  return (
    <div className="space-y-8">
      <PageHeader
        title={firstName ? `Welcome back, ${firstName}` : "Your workspace"}
        description={
          activeSession
            ? "You have one workspace running. Stop it when you are done so the GPU goes back into the pool."
            : "Start a workspace when you need one. Only one runs at a time."
        }
        actions={
          !activeSession && (
            <Button asChild>
              <Link href="/launch">
                <Plus className="h-4 w-4" aria-hidden="true" />
                Start a workspace
              </Link>
            </Button>
          )
        }
      />

      <div className="grid items-start gap-4 lg:grid-cols-2">
        {user && <BalanceCard balance={user.credit_balance} gpuRate={gpuRate} />}
        {activeSession ? (
          <SessionCard session={activeSession} onStopped={fetchData} />
        ) : (
          <EmptyState
            icon={Server}
            title="Nothing running"
            description="A GPU workspace opens JupyterLab with CUDA ready. A CPU workspace is the same environment without a GPU, and costs nothing."
            action={
              <Button size="sm" asChild>
                <Link href="/launch">Start a workspace</Link>
              </Button>
            }
          />
        )}
      </div>

      <section>
        <h2 className="text-sm font-medium text-foreground">Recent sessions</h2>

        {recentSessions.length === 0 ? (
          <p className="mt-3 text-sm text-muted-foreground">
            Sessions you have finished will be listed here, with how long each
            ran.
          </p>
        ) : (
          <div className="mt-3 overflow-x-auto rounded-md border border-border bg-card">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Environment</TableHead>
                  <TableHead>Hardware</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Ran for</TableHead>
                  <TableHead>Result</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {recentSessions.map((s) => {
                  const duration =
                    s.started_at && s.ended_at
                      ? elapsedMinutes(s.started_at, s.ended_at)
                      : null;
                  return (
                    <TableRow key={s.id}>
                      <TableCell className="font-medium text-foreground">
                        {s.image?.name ?? "Workspace"}
                      </TableCell>
                      <TableCell className="font-mono text-muted-foreground">
                        {s.resource_type === "l4_gpu" ? "NVIDIA L4" : "CPU"}
                      </TableCell>
                      <TableCell className="text-muted-foreground">
                        {formatDateTime(s.started_at)}
                      </TableCell>
                      <TableCell className="font-mono text-muted-foreground">
                        {duration !== null ? formatDuration(duration) : "—"}
                      </TableCell>
                      <TableCell>
                        <SessionStateBadge state={s.state} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </div>
        )}
      </section>
    </div>
  );
}
