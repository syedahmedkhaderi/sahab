"use client";

import React, { useEffect, useState } from "react";
import { BalanceCard } from "@/components/BalanceCard";
import { LedgerTable } from "@/components/LedgerTable";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { me, credits, rates as ratesApi } from "@/lib/api";
import type { User, LedgerEntry, Rate } from "@/lib/types";

const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "sahab-support@udst.edu.qa";

export default function BillingPage() {
  const [user, setUser] = useState<User | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [gpuRate, setGpuRate] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([me.get(), credits.ledger()])
      .then(([u, l]) => {
        setUser(u);
        setLedger(l);
      })
      .catch(() => {
        // The authed layout redirects on an expired session.
      })
      .finally(() => setLoading(false));

    ratesApi
      .list()
      .then((rs: Rate[]) => {
        const gpu = rs.find((r) => r.resource_type === "l4_gpu");
        if (gpu) setGpuRate(gpu.credits_per_minute);
      })
      .catch(() => {
        // The balance still reads correctly without the rate.
      });
  }, []);

  if (loading) {
    return (
      <div className="space-y-8">
        <Skeleton className="h-8 w-32" />
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-36" />
          <Skeleton className="h-36" />
        </div>
        <Skeleton className="h-64" />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <PageHeader
        title="Credits"
        description="What you have, and where it went. Credits are how two GPUs get shared fairly. No money changes hands."
      />

      <div className="grid items-start gap-4 lg:grid-cols-2">
        {user && (
          <BalanceCard balance={user.credit_balance} gpuRate={gpuRate} />
        )}

        {/* There is no top-up endpoint. A button here used to show a success
            alert without sending anything, telling people their request had been
            received when nothing had happened. */}
        <section className="rounded-md border border-border bg-card p-5">
          <h2 className="text-sm font-medium text-foreground">
            Getting more credits
          </h2>
          <p className="mt-2 text-sm text-muted-foreground">
            An administrator grants credits by hand. There is no request button
            here, because there is nothing for it to send. Email{" "}
            <a
              className="font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary"
              href={`mailto:${SUPPORT_EMAIL}?subject=Sahab%20credit%20request`}
            >
              {SUPPORT_EMAIL}
            </a>{" "}
            with your course or project and roughly how many hours you need.
          </p>
          <p className="mt-3 text-sm text-muted-foreground">
            A CPU workspace never uses credits, so you can keep working while you
            wait.
          </p>
        </section>
      </div>

      <section>
        <h2 className="text-sm font-medium text-foreground">History</h2>
        <div className="mt-3 overflow-x-auto rounded-md border border-border bg-card">
          <LedgerTable entries={ledger} />
        </div>
      </section>
    </div>
  );
}
