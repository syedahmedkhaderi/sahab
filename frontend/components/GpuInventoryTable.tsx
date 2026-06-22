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

interface GpuInventoryTableProps {
  gpus: GpuInventory[];
}

function statusVariant(
  status: GpuStatus
): "success" | "destructive" | "warning" | "secondary" {
  switch (status) {
    case "free":
      return "success";
    case "leased":
      return "warning";
    case "disabled":
      return "destructive";
    default:
      return "secondary";
  }
}

function vramLabel(mb: number): string {
  return `${Math.round(mb / 1024)} GB`;
}

export function GpuInventoryTable({ gpus }: GpuInventoryTableProps) {
  if (gpus.length === 0) {
    return (
      <div className="flex min-h-[120px] items-center justify-center rounded-lg border border-border text-muted-foreground">
        No GPUs found in inventory.
      </div>
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Model</TableHead>
          <TableHead>VRAM</TableHead>
          <TableHead>UUID</TableHead>
          <TableHead>Status</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {gpus.map((gpu) => (
          <TableRow key={gpu.id}>
            <TableCell className="font-medium">{gpu.model}</TableCell>
            <TableCell>{vramLabel(gpu.vram_mb)}</TableCell>
            <TableCell className="font-mono text-xs text-muted-foreground">
              {gpu.gpu_uuid}
            </TableCell>
            <TableCell>
              <Badge variant={statusVariant(gpu.status)}>
                {gpu.status.charAt(0).toUpperCase() + gpu.status.slice(1)}
              </Badge>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
