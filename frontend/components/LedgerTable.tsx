import React from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import type { LedgerEntry } from "@/lib/types";
import { formatCredits, formatDateTime, capitalize } from "@/lib/utils";

interface LedgerTableProps {
  entries: LedgerEntry[];
}

function reasonVariant(
  reason: string
): "success" | "destructive" | "secondary" | "outline" {
  switch (reason) {
    case "grant":
    case "refund":
      return "success";
    case "metering":
      return "destructive";
    default:
      return "secondary";
  }
}

export function LedgerTable({ entries }: LedgerTableProps) {
  if (entries.length === 0) {
    return (
      <div className="flex min-h-[160px] items-center justify-center rounded-lg border border-border text-muted-foreground">
        No transactions yet.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Date</TableHead>
          <TableHead>Type</TableHead>
          <TableHead className="text-right">Amount</TableHead>
          <TableHead className="text-right">Balance After</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {entries.map((entry) => (
          <TableRow key={entry.id}>
            <TableCell className="text-muted-foreground">
              {formatDateTime(entry.created_at)}
            </TableCell>
            <TableCell>
              <Badge variant={reasonVariant(entry.reason)}>
                {capitalize(entry.reason)}
              </Badge>
            </TableCell>
            <TableCell
              className={`text-right font-mono font-medium tabular-nums ${
                entry.delta > 0 ? "text-green-700" : "text-destructive"
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
