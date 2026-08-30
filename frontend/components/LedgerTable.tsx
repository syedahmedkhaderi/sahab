import React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { LedgerEntry } from "@/lib/types";
import { formatCredits, formatDateTime, capitalize } from "@/lib/utils";

interface LedgerTableProps {
  entries: LedgerEntry[];
}

/**
 * The ledger's own words, not the API's. "metering" is what the backend calls
 * the row; "GPU time" is what the money went on.
 */
function reasonLabel(reason: string): string {
  switch (reason) {
    case "grant":
      return "Granted by an administrator";
    case "refund":
      return "Refunded";
    case "metering":
      return "GPU time used";
    default:
      return capitalize(reason);
  }
}

export function LedgerTable({ entries }: LedgerTableProps) {
  if (entries.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border-strong px-5 py-8 text-sm text-muted-foreground">
        Nothing here yet. Credits granted to you and time you spend on a GPU will
        both show up in this list.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>What happened</TableHead>
          <TableHead className="text-right">Change</TableHead>
          <TableHead className="text-right">Balance after</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell className="text-muted-foreground">
              {formatDateTime(entry.created_at)}
            </TableCell>
            <TableCell className="text-foreground">
              {reasonLabel(entry.reason)}
            </TableCell>
            <TableCell
              className={`text-right font-mono font-medium tabular-nums ${
                entry.delta > 0 ? "text-success-strong" : "text-foreground"
              }`}
            >
              {entry.delta > 0 ? "+" : ""}
              {formatCredits(entry.delta)}
            </TableCell>
            <TableCell className="text-right font-mono tabular-nums text-muted-foreground">
              {formatCredits(entry.balance_after)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
