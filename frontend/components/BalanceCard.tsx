import React from "react";
import Link from "next/link";
import { formatCredits, creditsWithUnit } from "@/lib/utils";
import { cn } from "@/lib/utils";

interface BalanceCardProps {
  balance: number;
  /** Credits charged per minute of GPU time, when known. */
  gpuRate?: number | null;
  className?: string;
}

/**
 * The balance, and what it buys. A number on its own does not tell a student
 * whether they can start the run they had in mind — the hours do.
 */
export function BalanceCard({ balance, gpuRate, className }: BalanceCardProps) {
  const rate = gpuRate && gpuRate > 0 ? gpuRate : null;
  const minutesLeft = rate ? Math.floor(balance / rate) : null;

  const isEmpty = balance <= 0;
  // Under an hour of GPU time left, at the rate actually in force.
  const isLow = !isEmpty && minutesLeft !== null && minutesLeft < 60;

  return (
    <section
      className={cn(
        "rounded-md border bg-card p-5",
        isEmpty
          ? "border-destructive/40"
          : isLow
            ? "border-warning/40"
            : "border-border",
        className
      )}
    >
      <h2 className="text-sm font-medium text-muted-foreground">Credit balance</h2>

      <p className="mt-2 flex items-baseline gap-2">
        <span
          className={cn(
            "font-mono text-3xl font-semibold tabular-nums",
            isEmpty ? "text-destructive" : "text-foreground"
          )}
        >
          {formatCredits(balance)}
        </span>
        <span className="text-sm text-muted-foreground">credits</span>
      </p>

      <p className="mt-2 text-sm text-muted-foreground">
        {isEmpty ? (
          <>
            You cannot start a GPU workspace until an administrator grants you
            more. A CPU workspace is still free to use.
          </>
        ) : minutesLeft !== null ? (
          <>
            About{" "}
            <span className="font-medium text-foreground">
              {formatDuration(minutesLeft)}
            </span>{" "}
            of GPU time at {creditsWithUnit(rate!)} per minute.
          </>
        ) : (
          <>Charged per minute while a GPU workspace runs.</>
        )}
      </p>

      {(isEmpty || isLow) && (
        <Link
          href="/billing"
          className="mt-3 inline-block text-sm font-medium text-primary underline decoration-primary/30 underline-offset-4 hover:decoration-primary"
        >
          How to get more credits
        </Link>
      )}
    </section>
  );
}

function formatDuration(minutes: number): string {
  if (minutes < 60) return `${minutes} minutes`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (m === 0) return h === 1 ? "1 hour" : `${h} hours`;
  return `${h}h ${m}m`;
}
