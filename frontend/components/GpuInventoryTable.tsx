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
import type { GpuInventory, GpuStatus } from "@/lib/types";
import { formatVram } from "@/lib/utils";

interface GpuInventoryTableProps {
  gpus: GpuInventory[];
}

const STATUS: Record<
  GpuStatus,
  { label: string; variant: "success" | "warning" | "danger" | "outline" }
> = {
  free: { label: "Free", variant: "success" },
  leased: { label: "In use", variant: "warning" },
  disabled: { label: "Disabled", variant: "danger" },
};

/** Shortens a GPU UUID to the part an operator actually reads. */
function shortUuid(uuid: string): string {
  const withoutPrefix = uuid.replace(/^GPU-/, "");
  return withoutPrefix.slice(0, 8);
}

export function GpuInventoryTable({ gpus }: GpuInventoryTableProps) {
  if (gpus.length === 0) {
    return (
      <p className="px-4 py-6 text-sm text-muted-foreground">
        No GPUs are registered. Add a GPU server under{" "}
        <span className="font-medium text-foreground">VMs</span> — enrolling a
        machine registers its GPUs automatically.
      </p>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Model</TableHead>
          <TableHead>Machine</TableHead>
          <TableHead>Memory</TableHead>
          <TableHead>UUID</TableHead>
          <TableHead className="text-right">Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {gpus.map((gpu) => {
          const status = STATUS[gpu.status] ?? {
            label: gpu.status,
            variant: "outline" as const,
          };
          return (
            <TableRow key={gpu.id}>
              <TableCell className="whitespace-nowrap font-medium text-foreground">
                {gpu.model}
              </TableCell>
              {/* Which machine the card is in. With more than one GPU server,
                  "an L4 is free" is only half the answer. */}
              <TableCell className="whitespace-nowrap text-muted-foreground">
                {gpu.node_name ?? "—"}
              </TableCell>
              <TableCell className="whitespace-nowrap font-mono text-muted-foreground">
                {formatVram(gpu.vram_mb)}
              </TableCell>
              {/* The full UUID is the lease key, so it stays available on hover
                  and to a screen reader; the cell shows only the part that
                  distinguishes one card from the other. */}
              <TableCell
                className="font-mono text-xs text-muted-foreground"
                title={gpu.gpu_uuid}
              >
                {shortUuid(gpu.gpu_uuid)}
                <span className="sr-only"> (full identifier {gpu.gpu_uuid})</span>
              </TableCell>
              <TableCell className="text-right">
                <Badge variant={status.variant}>{status.label}</Badge>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
