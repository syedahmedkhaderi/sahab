"use client";

import React, { useState } from "react";
import { Plus, RefreshCw, Trash2, PauseCircle, PlayCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { AddNodeDialog } from "@/components/AddNodeDialog";
import { admin, ApiClientError } from "@/lib/api";
import type { GpuNode, NodeStatus } from "@/lib/types";
import { formatDateTime } from "@/lib/utils";

interface NodesPanelProps {
  nodes: GpuNode[];
  onChanged: () => void;
}

/**
 * What each state means, in the words an operator needs rather than the
 * internal name. "Draining" in particular is the one that needs explaining:
 * it is how a machine is taken out without interrupting anyone.
 */
const STATUS: Record<
  NodeStatus,
  { label: string; variant: "success" | "warning" | "danger" | "info" | "outline"; hint: string }
> = {
  ready: { label: "Ready", variant: "success", hint: "Taking new workspaces." },
  pending: { label: "Not set up", variant: "outline", hint: "Registered, but the machine has not run the join command yet." },
  enrolling: { label: "Enrolling", variant: "info", hint: "The install is running on the machine." },
  unreachable: { label: "Unreachable", variant: "danger", hint: "Its Docker API stopped answering." },
  draining: { label: "Draining", variant: "warning", hint: "Finishing its sessions; taking no new ones." },
  disabled: { label: "Disabled", variant: "outline", hint: "Out of the pool by hand." },
};

export function NodesPanel({ nodes, onChanged }: NodesPanelProps) {
  const { toast } = useToast();
  const [showAdd, setShowAdd] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const describeError = (e: unknown) =>
    e instanceof ApiClientError ? e.detail : e instanceof Error ? e.message : undefined;

  const run = async (id: string, action: () => Promise<unknown>, success: string) => {
    setBusyId(id);
    try {
      await action();
      toast({ tone: "success", title: success });
      onChanged();
    } catch (e) {
      toast({ tone: "error", title: "That did not work", description: describeError(e) });
    } finally {
      setBusyId(null);
    }
  };

  const setStatus = (node: GpuNode, status: "ready" | "draining") =>
    run(
      node.id,
      () => admin.updateNode(node.id, { status }),
      status === "draining"
        ? `${node.display_name ?? node.name} will take no new workspaces`
        : `${node.display_name ?? node.name} is back in the pool`,
    );

  const recheck = (node: GpuNode) =>
    run(node.id, () => admin.checkNode(node.id), `Checked ${node.display_name ?? node.name}`);

  const remove = (node: GpuNode) => {
    const label = node.display_name ?? node.name;
    if (!window.confirm(`Remove ${label} from Sahab? Its GPUs leave the pool.`)) return;
    run(node.id, () => admin.deleteNode(node.id), `${label} removed`);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <p className="text-sm text-muted-foreground">
          The machines that run workspaces. Adding one puts its GPUs into the
          pool automatically — users are placed on whichever machine has a free
          card.
        </p>
        <Button size="sm" onClick={() => setShowAdd(true)}>
          <Plus className="h-4 w-4" aria-hidden="true" />
          Add VM
        </Button>
      </div>

      {nodes.length === 0 ? (
        <EmptyState
          title="No GPU servers yet"
          description="Add a machine to put its GPUs into the pool."
          action={
            <Button size="sm" onClick={() => setShowAdd(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add VM
            </Button>
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-md border border-border bg-card">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Machine</TableHead>
                <TableHead>Address</TableHead>
                <TableHead>GPUs</TableHead>
                <TableHead>Driver</TableHead>
                <TableHead>Last seen</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {nodes.map((node) => {
                const status = STATUS[node.status] ?? {
                  label: node.status,
                  variant: "outline" as const,
                  hint: "",
                };
                const busy = busyId === node.id;
                return (
                  <TableRow key={node.id}>
                    <TableCell className="whitespace-nowrap font-medium text-foreground">
                      {node.display_name ?? node.name}
                      {node.is_manager && (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          control plane
                        </span>
                      )}
                      <div className="font-mono text-xs font-normal text-muted-foreground">
                        {node.name}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                      {node.address || "local socket"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap tabular-nums text-muted-foreground">
                      {node.gpus_total === 0 ? (
                        "—"
                      ) : (
                        <>
                          <span className="font-medium text-foreground">
                            {node.gpus_free}
                          </span>
                          {" free of "}
                          {node.gpus_total}
                        </>
                      )}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {node.driver_version ?? "—"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">
                      {node.last_seen_at ? formatDateTime(node.last_seen_at) : "never"}
                    </TableCell>
                    <TableCell>
                      <Badge variant={status.variant} title={status.hint}>
                        {status.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      <div className="flex justify-end gap-1">
                        {!node.is_manager && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => recheck(node)}
                            title="Probe this machine now"
                            aria-label={`Re-check ${node.display_name ?? node.name}`}
                          >
                            <RefreshCw className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        )}
                        {node.status === "draining" ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => setStatus(node, "ready")}
                            title="Put back into the pool"
                            aria-label={`Return ${node.display_name ?? node.name} to the pool`}
                          >
                            <PlayCircle className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        ) : (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy || node.status === "disabled"}
                            onClick={() => setStatus(node, "draining")}
                            title="Stop placing new workspaces here; let the running ones finish"
                            aria-label={`Drain ${node.display_name ?? node.name}`}
                          >
                            <PauseCircle className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        )}
                        {!node.is_manager && (
                          <Button
                            size="sm"
                            variant="ghost"
                            disabled={busy}
                            onClick={() => remove(node)}
                            title="Remove this machine from Sahab"
                            aria-label={`Remove ${node.display_name ?? node.name}`}
                          >
                            <Trash2 className="h-4 w-4" aria-hidden="true" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}

      <AddNodeDialog open={showAdd} onOpenChange={setShowAdd} onChanged={onChanged} />
    </div>
  );
}
