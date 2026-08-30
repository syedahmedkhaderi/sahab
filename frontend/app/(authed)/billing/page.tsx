"use client";

import React, { useEffect, useState } from "react";
import { Coins } from "lucide-react";
import { BalanceCard } from "@/components/BalanceCard";
import { LedgerTable } from "@/components/LedgerTable";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { me, credits } from "@/lib/api";
import type { User, LedgerEntry } from "@/lib/types";

const SUPPORT_EMAIL =
  process.env.NEXT_PUBLIC_SUPPORT_EMAIL || "sahab-support@udst.edu.qa";

export default function BillingPage() {
  const [user, setUser] = useState<User | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([me.get(), credits.ledger()])
      .then(([u, l]) => {
        setUser(u);
        setLedger(l);
      })
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-muted-foreground">
        Loading billing...
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <h1 className="text-2xl font-bold">Billing</h1>

      {/* Balance + top-up */}
      <div className="grid gap-4 sm:grid-cols-2">
        {user && <BalanceCard balance={user.credit_balance} />}

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Top Up Credits
            </CardTitle>
            <Coins className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent className="space-y-3">
            {/* There is no top-up endpoint yet. The button used to pop a success
                alert without sending anything, which told the user their request
                had been received when nothing had happened. Until a real request
                flow exists, this says what actually gets a student more credits. */}
            <p className="text-sm text-muted-foreground">
              Credits are granted by a platform administrator. Email{" "}
              <a
                className="font-medium text-primary underline underline-offset-4"
                href={`mailto:${SUPPORT_EMAIL}?subject=Sahab%20credit%20request`}
              >
                {SUPPORT_EMAIL}
              </a>{" "}
              with your course or project and how many hours you need.
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Ledger */}
      <div>
        <h2 className="mb-4 text-base font-semibold">Transaction history</h2>
        <LedgerTable entries={ledger} />
      </div>
    </div>
  );
}
