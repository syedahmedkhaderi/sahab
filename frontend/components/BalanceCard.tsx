import React from "react";
import { Coins, TrendingDown } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatCredits } from "@/lib/utils";

interface BalanceCardProps {
  balance: number;
  className?: string;
}

export function BalanceCard({ balance, className }: BalanceCardProps) {
  const isLow = balance > 0 && balance < 60; // less than one hour of GPU time
  const isEmpty = balance <= 0;

  return (
    <Card className={className}>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium text-muted-foreground">
          Credit Balance
        </CardTitle>
        <Coins className="h-4 w-4 text-muted-foreground" />
      </CardHeader>
      <CardContent>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold tabular-nums">
            {formatCredits(balance)}
          </span>
          <span className="text-sm text-muted-foreground">credits</span>
        </div>
        <div className="mt-2 flex items-center gap-2">
          {isEmpty && (
            <Badge variant="destructive" className="flex items-center gap-1">
              <TrendingDown className="h-3 w-3" />
              Out of credits
            </Badge>
          )}
          {isLow && !isEmpty && (
            <Badge variant="warning" className="flex items-center gap-1">
              <TrendingDown className="h-3 w-3" />
              Low balance
            </Badge>
          )}
          {!isEmpty && !isLow && (
            <p className="text-xs text-muted-foreground">
              ~{Math.floor(balance / 60)}h {Math.floor((balance % 60))}m of GPU time remaining
            </p>
          )}
        </div>
        {isEmpty && (
          <p className="mt-1 text-xs text-muted-foreground">
            Contact an administrator to top up your credits.
          </p>
        )}
      </CardContent>
    </Card>
  );
}
