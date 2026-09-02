"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  Server,
  Activity,
  Coins,
  Plus,
  Square,
  RefreshCw,
  Box,
  HardDrive,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs, TabPanel, type TabItem } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/toast";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { Select } from "@/components/ui/select";
import { GpuInventoryTable } from "@/components/GpuInventoryTable";
import { NodesPanel } from "@/components/NodesPanel";
import { SessionStateBadge } from "@/components/SessionStateBadge";
import { me, admin, rates as ratesApi, images as imagesApi } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type {
  User,
  Session,
  GpuInventory,
  GpuNode,
  Rate,
  AdminMetrics,
  Image,
} from "@/lib/types";
import { formatCredits, formatDateTime, capitalize } from "@/lib/utils";

type AdminTab =
  | "overview"
  | "users"
  | "sessions"
  | "nodes"
  | "gpus"
  | "rates"
  | "images";

const ACTIVE_STATES = ["starting", "running", "queued"];

/** Wraps a table so a wide one scrolls inside its own panel, not the page. */
function TablePanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border bg-card">
      {children}
    </div>
  );
}

export default function AdminPage() {
  const router = useRouter();
  const { toast } = useToast();
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");

  const [users, setUsers] = useState<User[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [gpus, setGpus] = useState<GpuInventory[]>([]);
  const [nodes, setNodes] = useState<GpuNode[]>([]);
  const [rates, setRates] = useState<Rate[]>([]);
  const [images, setImages] = useState<Image[]>([]);
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [grantTarget, setGrantTarget] = useState<User | null>(null);
  const [grantAmount, setGrantAmount] = useState("");
  const [granting, setGranting] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);

  const [showImageDialog, setShowImageDialog] = useState(false);
  const [newImage, setNewImage] = useState({
    name: "",
    docker_ref: "",
    kind: "gpu" as "gpu" | "cpu",
  });
  const [savingImage, setSavingImage] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);

  const fetchAll = useCallback(async () => {
    try {
      const u = await me.get();
      if (u.role !== "admin") {
        router.replace("/dashboard");
        return;
      }

      // Rates and images are ordinary authenticated endpoints, fetched through
      // the same client as everything else so their failures surface the same
      // way. They used to be raw fetch() calls labelled "public endpoint",
      // which they are not — a failure there returned an error body that was
      // then rendered as if it were a list.
      const [us, ss, gs, ns, rs, ms, imgs] = await Promise.all([
        admin.listUsers(),
        admin.listSessions(),
        admin.listGpus(),
        admin.listNodes(),
        ratesApi.list(),
        admin.metrics(),
        imagesApi.list(),
      ]);
      setUsers(us);
      setSessions(ss);
      setGpus(gs);
      setNodes(ns);
      setRates(rs);
      setMetrics(ms);
      setImages(imgs);
      setError(null);
    } catch (e) {
      if (e instanceof ApiClientError && e.status === 401) {
        router.replace("/login");
      } else {
        setError("Could not load the console. The API may be unreachable.");
      }
    } finally {
      setLoading(false);
    }
  }, [router]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 15_000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const manualRefresh = async () => {
    setRefreshing(true);
    await fetchAll();
    setRefreshing(false);
  };

  const handleForceStop = async (session: Session) => {
    try {
      await admin.stopSession(session.id);
      toast({
        tone: "success",
        title: "Session stopped",
        description: `${session.user_email ?? "The session"} was stopped.`,
      });
      fetchAll();
    } catch (e) {
      toast({
        tone: "error",
        title: "Could not stop that session",
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  const handleGrantCredits = async () => {
    if (!grantTarget) return;
    const amount = parseFloat(grantAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setGrantError("Enter an amount greater than zero.");
      return;
    }

    setGranting(true);
    setGrantError(null);
    try {
      await admin.grantCredits(grantTarget.id, { amount, reason: "grant" });
      toast({
        tone: "success",
        title: "Credits granted",
        description: `${formatCredits(amount)} credits to ${grantTarget.email}.`,
      });
      setGrantTarget(null);
      setGrantAmount("");
      fetchAll();
    } catch (e) {
      setGrantError(e instanceof Error ? e.message : "Could not grant credits.");
    } finally {
      setGranting(false);
    }
  };

  const handleUpdateUserStatus = async (user: User, status: "active" | "disabled") => {
    try {
      await admin.updateUser(user.id, { status });
      toast({
        tone: "success",
        title: status === "active" ? "Account activated" : "Account disabled",
        description: user.email,
      });
      fetchAll();
    } catch (e) {
      toast({
        tone: "error",
        title: "Could not update that account",
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  const handleSaveImage = async () => {
    setSavingImage(true);
    setImageError(null);
    try {
      await admin.createImage(newImage);
      toast({ tone: "success", title: "Environment added", description: newImage.name });
      setShowImageDialog(false);
      setNewImage({ name: "", docker_ref: "", kind: "gpu" });
      fetchAll();
    } catch (e) {
      setImageError(e instanceof Error ? e.message : "Could not add the environment.");
    } finally {
      setSavingImage(false);
    }
  };

  const handleToggleImage = async (img: Image) => {
    try {
      await admin.updateImage(img.id, { enabled: !img.enabled });
      fetchAll();
    } catch (e) {
      toast({
        tone: "error",
        title: "Could not change that environment",
        description: e instanceof Error ? e.message : undefined,
      });
    }
  };

  const activeSessions = useMemo(
    () => sessions.filter((s) => ACTIVE_STATES.includes(s.state)),
    [sessions]
  );
  const pendingUsers = useMemo(
    () => users.filter((u) => u.status === "pending"),
    [users]
  );
  const unreachableNodes = useMemo(
    () => nodes.filter((n) => n.status === "unreachable"),
    [nodes]
  );

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-10 w-full" />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
      </div>
    );
  }

  const tabs: readonly TabItem<AdminTab>[] = [
    { id: "overview", label: "Overview", icon: <Activity className="h-4 w-4" /> },
    {
      id: "users",
      label: "People",
      icon: <Users className="h-4 w-4" />,
      badge: pendingUsers.length > 0 ? pendingUsers.length : undefined,
    },
    {
      id: "sessions",
      label: "Sessions",
      icon: <Activity className="h-4 w-4" />,
      badge: activeSessions.length > 0 ? activeSessions.length : undefined,
    },
    {
      id: "nodes",
      label: "VMs",
      icon: <HardDrive className="h-4 w-4" />,
      // An unreachable machine is the one thing here worth interrupting for:
      // its GPUs have left the pool and someone's session was failed.
      badge: unreachableNodes.length > 0 ? unreachableNodes.length : undefined,
    },
    { id: "gpus", label: "GPUs", icon: <Server className="h-4 w-4" /> },
    { id: "rates", label: "Rates", icon: <Coins className="h-4 w-4" /> },
    { id: "images", label: "Environments", icon: <Box className="h-4 w-4" /> },
  ];

  const totalGpus =
    metrics === null
      ? 0
      : metrics.gpus_free + metrics.gpus_leased + metrics.gpus_disabled;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Admin console"
        description="Accounts, sessions, hardware and rates for this deployment."
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={manualRefresh}
            loading={refreshing}
          >
            {!refreshing && <RefreshCw className="h-4 w-4" aria-hidden="true" />}
            Refresh
          </Button>
        }
      />

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Tabs
        items={tabs}
        value={activeTab}
        onValueChange={setActiveTab}
        label="Admin sections"
      />

      <TabPanel id="overview" active={activeTab === "overview"}>
        {metrics && (
          <div className="space-y-6">
            <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {[
                { label: "Sessions running", value: String(metrics.active_sessions) },
                { label: "Waiting for a GPU", value: String(metrics.queued_sessions) },
                {
                  label: "GPUs free",
                  value: `${metrics.gpus_free} / ${totalGpus}`,
                },
                {
                  // The API reports a cumulative total, not a rolling window,
                  // so the label says so rather than implying a rate.
                  label: "Credits used to date",
                  value: formatCredits(metrics.total_credits_used),
                },
              ].map(({ label, value }) => (
                <div
                  key={label}
                  className="rounded-md border border-border bg-card px-4 py-3.5"
                >
                  <dt className="text-xs text-muted-foreground">{label}</dt>
                  <dd className="mt-1 font-mono text-2xl font-semibold tabular-nums text-foreground">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>

            {pendingUsers.length > 0 && (
              <Alert variant="warning">
                <AlertDescription>
                  {pendingUsers.length === 1
                    ? "One account is waiting for approval and cannot launch anything yet."
                    : `${pendingUsers.length} accounts are waiting for approval and cannot launch anything yet.`}{" "}
                  <button
                    type="button"
                    onClick={() => setActiveTab("users")}
                    className="font-medium underline underline-offset-4"
                  >
                    Review them
                  </button>
                </AlertDescription>
              </Alert>
            )}

            <div className="grid gap-4 lg:grid-cols-2">
              <section className="rounded-md border border-border bg-card">
                <h2 className="border-b border-border px-4 py-3 text-sm font-medium text-foreground">
                  GPU inventory
                </h2>
                <div className="overflow-x-auto">
                  <GpuInventoryTable gpus={gpus} />
                </div>
              </section>

              <section className="rounded-md border border-border bg-card">
                <h2 className="border-b border-border px-4 py-3 text-sm font-medium text-foreground">
                  Sessions running now
                </h2>
                {activeSessions.length === 0 ? (
                  <p className="px-4 py-6 text-sm text-muted-foreground">
                    Nobody is using a workspace at the moment.
                  </p>
                ) : (
                  <ul className="divide-y divide-border">
                    {activeSessions.map((s) => (
                      <li
                        key={s.id}
                        className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
                      >
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-sm text-foreground">
                            {s.user_email ?? s.user_id}
                          </span>
                          <span className="block font-mono text-xs text-muted-foreground">
                            {s.resource_type === "l4_gpu" ? "NVIDIA L4" : "CPU"}
                          </span>
                        </span>
                        <span className="flex items-center gap-2">
                          <SessionStateBadge state={s.state} />
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-destructive hover:bg-destructive-subtle"
                            onClick={() => handleForceStop(s)}
                          >
                            Stop
                          </Button>
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>
          </div>
        )}
      </TabPanel>

      <TabPanel id="users" active={activeTab === "users"}>
        <TablePanel>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Balance</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <span className="block font-medium text-foreground">
                      {u.full_name ?? "—"}
                    </span>
                    <span className="block text-xs text-muted-foreground">
                      {u.email}
                    </span>
                  </TableCell>
                  <TableCell className="text-muted-foreground">
                    {capitalize(u.role)}
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant={
                        u.status === "active"
                          ? "success"
                          : u.status === "pending"
                            ? "warning"
                            : "outline"
                      }
                    >
                      {capitalize(u.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums text-foreground">
                    {formatCredits(u.credit_balance)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-1.5">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => {
                          setGrantError(null);
                          setGrantTarget(u);
                        }}
                      >
                        <Plus className="h-3 w-3" aria-hidden="true" />
                        Credits
                      </Button>
                      {u.status === "active" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleUpdateUserStatus(u, "disabled")}
                          className="text-destructive hover:bg-destructive-subtle"
                        >
                          Disable
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleUpdateUserStatus(u, "active")}
                        >
                          {u.status === "pending" ? "Approve" : "Activate"}
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TablePanel>
      </TabPanel>

      <TabPanel id="sessions" active={activeTab === "sessions"}>
        {sessions.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No sessions yet"
            description="Every workspace launched on this deployment will be listed here, including the ones that failed."
          />
        ) : (
          <TablePanel>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Person</TableHead>
                  <TableHead>Hardware</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {sessions.slice(0, 50).map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      <span className="block truncate text-foreground">
                        {s.user_email ?? s.user_id}
                      </span>
                      {s.user_full_name && (
                        <span className="block text-xs text-muted-foreground">
                          {s.user_full_name}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      {s.resource_type === "l4_gpu" ? "NVIDIA L4" : "CPU"}
                      {/* With more than one GPU server, "a session is running"
                          is only half an answer — which machine matters when
                          one of them is misbehaving. */}
                      {s.node_name && (
                        <span className="block text-xs">{s.node_name}</span>
                      )}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(s.started_at ?? s.created_at)}
                    </TableCell>
                    <TableCell>
                      <SessionStateBadge state={s.state} />
                    </TableCell>
                    <TableCell className="text-right">
                      {ACTIVE_STATES.includes(s.state) && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => handleForceStop(s)}
                          className="text-destructive hover:bg-destructive-subtle"
                        >
                          <Square className="h-3 w-3" aria-hidden="true" />
                          Force stop
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TablePanel>
        )}
      </TabPanel>

      <TabPanel id="nodes" active={activeTab === "nodes"}>
        <NodesPanel nodes={nodes} onChanged={fetchAll} />
      </TabPanel>

      <TabPanel id="gpus" active={activeTab === "gpus"}>
        <div className="space-y-3">
          <p className="max-w-prose text-sm text-muted-foreground">
            Status is what Sahab has leased. A GPU can read as free here while a
            job started outside the platform is using it. The scheduler checks
            live utilisation before assigning one, so it skips a busy GPU rather
            than handing it out.
          </p>
          <TablePanel>
            <GpuInventoryTable gpus={gpus} />
          </TablePanel>
        </div>
      </TabPanel>

      <TabPanel id="rates" active={activeTab === "rates"}>
        <div className="max-w-prose space-y-4">
          <p className="text-sm text-muted-foreground">
            What one minute of each kind of workspace costs a user. Changes apply
            to sessions started afterwards.
          </p>
          <div className="divide-y divide-border rounded-md border border-border bg-card">
            {rates.map((rate) => (
              <div key={rate.id} className="p-4">
                <RateEditor rate={rate} onSaved={fetchAll} />
              </div>
            ))}
          </div>
        </div>
      </TabPanel>

      <TabPanel id="images" active={activeTab === "images"}>
        <div className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <p className="max-w-prose text-sm text-muted-foreground">
              The container images a user can pick when starting a workspace.
            </p>
            <Button
              size="sm"
              onClick={() => {
                setImageError(null);
                setShowImageDialog(true);
              }}
            >
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add
            </Button>
          </div>
          <TablePanel>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Hardware</TableHead>
                  <TableHead>Image</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {images.map((img) => (
                  <TableRow key={img.id}>
                    <TableCell className="font-medium text-foreground">
                      {img.name}
                    </TableCell>
                    <TableCell className="font-mono text-muted-foreground">
                      {img.kind === "gpu" ? "GPU" : "CPU"}
                    </TableCell>
                    <TableCell className="max-w-[18rem] truncate font-mono text-xs text-muted-foreground">
                      {img.docker_ref}
                    </TableCell>
                    <TableCell>
                      <Badge variant={img.enabled ? "success" : "outline"}>
                        {img.enabled ? "Enabled" : "Disabled"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleToggleImage(img)}
                      >
                        {img.enabled ? "Disable" : "Enable"}
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TablePanel>
        </div>
      </TabPanel>

      {/* Grant credits */}
      <Dialog
        open={!!grantTarget}
        onOpenChange={(open) => !open && setGrantTarget(null)}
      >
        <DialogContent onClose={() => setGrantTarget(null)}>
          <DialogHeader>
            <DialogTitle>Grant credits</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Adding credits to{" "}
              <span className="font-medium text-foreground">
                {grantTarget?.email}
              </span>
              . Their balance is currently{" "}
              <span className="font-mono">
                {formatCredits(grantTarget?.credit_balance ?? 0)}
              </span>
              .
            </p>
            <div className="space-y-1.5">
              <Label htmlFor="amount">Credits to add</Label>
              <Input
                id="amount"
                type="number"
                min="1"
                step="1"
                value={grantAmount}
                onChange={(e) => setGrantAmount(e.target.value)}
                placeholder="240"
              />
              <p className="text-xs text-muted-foreground">
                240 credits is roughly four hours of GPU time at the current rate.
              </p>
            </div>
            {grantError && (
              <Alert variant="destructive">
                <AlertDescription>{grantError}</AlertDescription>
              </Alert>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGrantTarget(null)}>
              Cancel
            </Button>
            <Button onClick={handleGrantCredits} loading={granting}>
              Grant credits
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add environment */}
      <Dialog open={showImageDialog} onOpenChange={setShowImageDialog}>
        <DialogContent onClose={() => setShowImageDialog(false)}>
          <DialogHeader>
            <DialogTitle>Add an environment</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label htmlFor="imgName">Name people will see</Label>
              <Input
                id="imgName"
                value={newImage.name}
                onChange={(e) => setNewImage((p) => ({ ...p, name: e.target.value }))}
                placeholder="PyTorch 2.x (CUDA 12)"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="imgRef">Docker image</Label>
              <Input
                id="imgRef"
                className="font-mono"
                value={newImage.docker_ref}
                onChange={(e) =>
                  setNewImage((p) => ({ ...p, docker_ref: e.target.value }))
                }
                placeholder="sahab-gpu-pytorch:latest"
              />
              <p className="text-xs text-muted-foreground">
                It must already be present on this host. Nothing is pulled for you.
              </p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="imgKind">Hardware</Label>
              <Select
                id="imgKind"
                value={newImage.kind}
                onChange={(e) =>
                  setNewImage((p) => ({ ...p, kind: e.target.value as "gpu" | "cpu" }))
                }
              >
                <option value="gpu">GPU</option>
                <option value="cpu">CPU</option>
              </Select>
            </div>
            {imageError && (
              <Alert variant="destructive">
                <AlertDescription>{imageError}</AlertDescription>
              </Alert>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowImageDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSaveImage}
              loading={savingImage}
              disabled={!newImage.name || !newImage.docker_ref}
            >
              Add environment
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** Inline editor for one pricing rate. */
function RateEditor({ rate, onSaved }: { rate: Rate; onSaved: () => void }) {
  const [value, setValue] = useState(rate.credits_per_minute.toString());
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { toast } = useToast();

  const label =
    rate.resource_type === "l4_gpu" ? "GPU workspace" : "CPU workspace";

  const handleSave = async () => {
    const parsed = parseFloat(value);
    if (!Number.isFinite(parsed) || parsed < 0) {
      setSaveError("Enter a rate of 0 or more.");
      return;
    }

    setSaving(true);
    setSaveError(null);
    try {
      await admin.setRate({
        resource_type: rate.resource_type,
        credits_per_minute: parsed,
      });
      toast({
        tone: "success",
        title: "Rate saved",
        description: `${label} is now ${formatCredits(parsed)} credits per minute.`,
      });
      onSaved();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save this rate.");
    } finally {
      setSaving(false);
    }
  };

  const inputId = `rate-${rate.resource_type}`;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <Label htmlFor={inputId} className="text-sm font-medium text-foreground">
            {label}
          </Label>
          <p className="mt-0.5 text-xs text-muted-foreground">Credits per minute</p>
        </div>
        <Input
          id={inputId}
          type="number"
          min="0"
          step="0.1"
          className="w-28 font-mono"
          value={value}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button size="sm" onClick={handleSave} loading={saving}>
          Save
        </Button>
      </div>
      {saveError && (
        <p className="text-sm text-destructive" role="alert">
          {saveError}
        </p>
      )}
    </div>
  );
}
