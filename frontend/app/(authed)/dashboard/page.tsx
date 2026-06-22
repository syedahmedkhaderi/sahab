"use client";

import React, { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Plus, History } from "lucide-react";
import { Button } from "@/components/ui/button";
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
import { me, sessions as sessionsApi } from "@/lib/api";
import type { User, Session } from "@/lib/types";
import { formatDateTime, elapsedMinutes, formatDuration } from "@/lib/utils";

export default function DashboardPage() {
  const [user, setUser] = useState<User | null>(null);
  const [sessionList, setSessionList] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);

  const ACTIVE_STATES = ["requested", "queued", "starting", "running", "stopping"];

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
    // Poll while there is an active session
    const interval = setInterval(() => {
      fetchData();
    }, 10_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const activeSession = sessionList.find((s) =>
    ACTIVE_STATES.includes(s.state)
  );
  const recentSessions = sessionList
    .filter((s) => s.state === "stopped" || s.state === "failed")
    .slice(0, 5);

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-muted-foreground">
        Loading dashboard...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Page heading */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Dashboard</h1>
        {!activeSession && (
          <Link href="/launch">
            <Button className="flex items-center gap-2">
              <Plus className="h-4 w-4" />
              Launch Workspace
            </Button>
          </Link>
        )}
      </div>

      {/* Top cards */}
      <div className="grid gap-4 sm:grid-cols-2">
        {user && <BalanceCard balance={user.credit_balance} />}
        {activeSession ? (
          <SessionCard session={activeSession} onStopped={fetchData} />
        ) : (
          <div className="flex flex-col items-center justify-center rounded-lg border border-dashed border-border p-8 text-center">
            <p className="text-sm font-medium text-muted-foreground">
              No active session
            </p>
            <Link href="/launch" className="mt-3">
              <Button size="sm">Launch Workspace</Button>
            </Link>
          </div>
        )}
      </div>

      {/* Recent sessions */}
      <div>
        <div className="mb-4 flex items-center gap-2">
          <History className="h-4 w-4 text-muted-foreground" />
          <h2 className="text-base font-semibold">Recent Sessions</h2>
        </div>

        {recentSessions.length === 0 ? (
          <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-border text-sm text-muted-foreground">
            No past sessions yet.
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Environment</TableHead>
                <TableHead>Runtime</TableHead>
                <TableHead>Started</TableHead>
                <TableHead>Duration</TableHead>
                <TableHead>Status</TableHead>
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
                    <TableCell className="font-medium">
                      {s.image?.name ?? "Workspace"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {s.resource_type === "l4_gpu" ? "GPU" : "CPU"}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(s.started_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
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
        )}
      </div>
    </div>
  );
}
