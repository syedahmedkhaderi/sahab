"use client";

import React, { useEffect, useState } from "react";
import { Coins, ArrowUpRight } from "lucide-react";
import { BalanceCard } from "@/components/BalanceCard";
import { LedgerTable } from "@/components/LedgerTable";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { me, credits } from "@/lib/api";
import type { User, LedgerEntry } from "@/lib/types";

export default function BillingPage() {
  const [user, setUser] = useState<User | null>(null);
  const [ledger, setLedger] = useState<LedgerEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [topUpSent, setTopUpSent] = useState(false);

  useEffect(() => {
    Promise.all([me.get(), credits.ledger()])
      .then(([u, l]) => {
        setUser(u);
        setLedger(l);
      })
      .finally(() => setLoading(false));
  }, []);

  const handleTopUpRequest = () => {
    // In MVP, direct user to contact admin. A richer flow would POST a request.
    setTopUpSent(true);
  };

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
            <p className="text-sm text-muted-foreground">
              Credits are granted by a platform administrator. Contact your admin to request
              additional compute credits.
            </p>
            {topUpSent ? (
              <Alert variant="success">
                <AlertDescription>
                  Top-up request noted. Contact your administrator to proceed.
                </AlertDescription>
              </Alert>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="flex items-center gap-1.5"
                onClick={handleTopUpRequest}
              >
                <ArrowUpRight className="h-4 w-4" />
                Request top-up
              </Button>
            )}
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
