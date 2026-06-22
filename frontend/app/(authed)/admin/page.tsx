"use client";

import React, { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Users,
  Server,
  Activity,
  DollarSign,
  Plus,
  Square,
  RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
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
import { SessionStateBadge } from "@/components/SessionStateBadge";
import { me, admin } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { User, Session, GpuInventory, Rate, AdminMetrics, Image } from "@/lib/types";
import { formatCredits, formatDateTime, capitalize } from "@/lib/utils";

type AdminTab = "overview" | "users" | "sessions" | "gpus" | "rates" | "images";

export default function AdminPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<AdminTab>("overview");

  // Data
  const [currentUser, setCurrentUser] = useState<User | null>(null);
  const [users, setUsers] = useState<User[]>([]);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [gpus, setGpus] = useState<GpuInventory[]>([]);
  const [rates, setRates] = useState<Rate[]>([]);
  const [images, setImages] = useState<Image[]>([]);
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Grant credits dialog
  const [grantTarget, setGrantTarget] = useState<User | null>(null);
  const [grantAmount, setGrantAmount] = useState("");
  const [grantReason, setGrantReason] = useState("grant");
  const [granting, setGranting] = useState(false);
  const [grantError, setGrantError] = useState<string | null>(null);

  // Image dialog
  const [showImageDialog, setShowImageDialog] = useState(false);
  const [newImage, setNewImage] = useState({ name: "", docker_ref: "", kind: "gpu" as "gpu" | "cpu" });
  const [savingImage, setSavingImage] = useState(false);

  const fetchAll = useCallback(async () => {
    try {
      const u = await me.get();
      if (u.role !== "admin") {
        router.replace("/dashboard");
        return;
      }
      setCurrentUser(u);

      const [us, ss, gs, rs, ms, imgs] = await Promise.all([
        admin.listUsers(),
        admin.listSessions(),
        admin.listGpus(),
        // rates come from public endpoint
        fetch("/api/rates").then((r) => r.json()) as Promise<Rate[]>,
        admin.metrics(),
        // images from public endpoint
        fetch("/api/images").then((r) => r.json()) as Promise<Image[]>,
      ]);
      setUsers(us);
      setSessions(ss);
      setGpus(gs);
      setRates(rs);
      setMetrics(ms);
      setImages(imgs);
    } catch (e) {
      if (e instanceof ApiClientError && e.status === 401) {
        router.replace("/login");
      } else {
        setError("Failed to load admin data.");
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

  const handleForceStop = async (sessionId: string) => {
    try {
      await admin.stopSession(sessionId);
      fetchAll();
    } catch {
      setError("Failed to stop session.");
    }
  };

  const handleGrantCredits = async () => {
    if (!grantTarget || !grantAmount) return;
    setGranting(true);
    setGrantError(null);
    try {
      await admin.grantCredits(grantTarget.id, {
        amount: parseFloat(grantAmount),
        reason: grantReason,
      });
      setGrantTarget(null);
      setGrantAmount("");
      fetchAll();
    } catch (e) {
      setGrantError(e instanceof Error ? e.message : "Failed to grant credits.");
    } finally {
      setGranting(false);
    }
  };

  const handleUpdateUserStatus = async (userId: string, status: "active" | "disabled") => {
    try {
      await admin.updateUser(userId, { status });
      fetchAll();
    } catch {
      setError("Failed to update user.");
    }
  };

  const handleSaveImage = async () => {
    setSavingImage(true);
    try {
      await admin.createImage(newImage);
      setShowImageDialog(false);
      setNewImage({ name: "", docker_ref: "", kind: "gpu" });
      fetchAll();
    } catch {
      // keep dialog open on error
    } finally {
      setSavingImage(false);
    }
  };

  const handleToggleImage = async (img: Image) => {
    await admin.updateImage(img.id, { enabled: !img.enabled });
    fetchAll();
  };

  if (loading) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center text-muted-foreground">
        Loading admin console...
      </div>
    );
  }

  const tabs: { id: AdminTab; label: string; icon: React.ReactNode }[] = [
    { id: "overview", label: "Overview", icon: <Activity className="h-4 w-4" /> },
    { id: "users", label: "Users", icon: <Users className="h-4 w-4" /> },
    { id: "sessions", label: "Sessions", icon: <Activity className="h-4 w-4" /> },
    { id: "gpus", label: "GPUs", icon: <Server className="h-4 w-4" /> },
    { id: "rates", label: "Rates", icon: <DollarSign className="h-4 w-4" /> },
    { id: "images", label: "Images", icon: <Server className="h-4 w-4" /> },
  ];

  const activeSessions = sessions.filter((s) =>
    ["starting", "running", "queued"].includes(s.state)
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Admin Console</h1>
        <Button variant="outline" size="sm" onClick={fetchAll} className="flex items-center gap-1.5">
          <RefreshCw className="h-4 w-4" />
          Refresh
        </Button>
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {/* Tab bar */}
      <div className="flex flex-wrap gap-1 border-b border-border pb-1">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
              activeTab === tab.id
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            }`}
          >
            {tab.icon}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Overview tab */}
      {activeTab === "overview" && metrics && (
        <div className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { label: "Active Sessions", value: metrics.active_sessions },
              { label: "Queued", value: metrics.queued_sessions },
              {
                label: "GPUs Available",
                value: `${metrics.free_gpus} / ${metrics.total_gpus}`,
              },
              {
                label: "Credits Burned / hr",
                value: formatCredits(metrics.credits_burned_last_hour),
              },
            ].map(({ label, value }) => (
              <Card key={label}>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm font-medium text-muted-foreground">
                    {label}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-bold tabular-nums">{value}</p>
                </CardContent>
              </Card>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            {/* GPU inventory summary */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">GPU Status</CardTitle>
              </CardHeader>
              <CardContent>
                <GpuInventoryTable gpus={gpus} />
              </CardContent>
            </Card>

            {/* Active sessions summary */}
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Active Sessions</CardTitle>
              </CardHeader>
              <CardContent>
                {activeSessions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No active sessions.</p>
                ) : (
                  <ul className="space-y-2">
                    {activeSessions.map((s) => (
                      <li key={s.id} className="flex items-center justify-between text-sm">
                        <span className="text-muted-foreground">
                          {s.user?.email ?? s.user_id}
                        </span>
                        <div className="flex items-center gap-2">
                          <SessionStateBadge state={s.state} />
                          <button
                            onClick={() => handleForceStop(s.id)}
                            className="text-xs text-destructive hover:underline"
                          >
                            Stop
                          </button>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Users tab */}
      {activeTab === "users" && (
        <div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name / Email</TableHead>
                <TableHead>Role</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="text-right">Balance</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.map((u) => (
                <TableRow key={u.id}>
                  <TableCell>
                    <p className="font-medium">{u.full_name ?? "—"}</p>
                    <p className="text-xs text-muted-foreground">{u.email}</p>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{capitalize(u.role)}</Badge>
                  </TableCell>
                  <TableCell>
                    <Badge variant={u.status === "active" ? "success" : "warning"}>
                      {capitalize(u.status)}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {formatCredits(u.credit_balance)}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => setGrantTarget(u)}
                      >
                        <Plus className="mr-1 h-3 w-3" />
                        Credits
                      </Button>
                      {u.status === "active" ? (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleUpdateUserStatus(u.id, "disabled")}
                          className="text-destructive"
                        >
                          Disable
                        </Button>
                      ) : (
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() => handleUpdateUserStatus(u.id, "active")}
                        >
                          Activate
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      {/* Sessions tab */}
      {activeTab === "sessions" && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>User</TableHead>
              <TableHead>Runtime</TableHead>
              <TableHead>Started</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {sessions.slice(0, 50).map((s) => (
              <TableRow key={s.id}>
                <TableCell className="text-sm text-muted-foreground">
                  {s.user?.email ?? s.user_id}
                </TableCell>
                <TableCell>{s.resource_type === "l4_gpu" ? "GPU" : "CPU"}</TableCell>
                <TableCell className="text-muted-foreground">
                  {formatDateTime(s.started_at)}
                </TableCell>
                <TableCell>
                  <SessionStateBadge state={s.state} />
                </TableCell>
                <TableCell>
                  {["starting", "running", "queued"].includes(s.state) && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleForceStop(s.id)}
                      className="flex items-center gap-1 text-destructive"
                    >
                      <Square className="h-3 w-3" />
                      Force stop
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {/* GPUs tab */}
      {activeTab === "gpus" && (
        <div>
          <GpuInventoryTable gpus={gpus} />
        </div>
      )}

      {/* Rates tab */}
      {activeTab === "rates" && (
        <div className="max-w-md space-y-4">
          {rates.map((rate) => (
            <Card key={rate.id}>
              <CardContent className="pt-4">
                <RateEditor
                  rate={rate}
                  onSaved={fetchAll}
                />
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Images tab */}
      {activeTab === "images" && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <Button
              size="sm"
              onClick={() => setShowImageDialog(true)}
              className="flex items-center gap-1.5"
            >
              <Plus className="h-4 w-4" />
              Add image
            </Button>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Docker ref</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {images.map((img) => (
                <TableRow key={img.id}>
                  <TableCell className="font-medium">{img.name}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{img.kind.toUpperCase()}</Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">
                    {img.docker_ref}
                  </TableCell>
                  <TableCell>
                    <Badge variant={img.enabled ? "success" : "outline"}>
                      {img.enabled ? "Enabled" : "Disabled"}
                    </Badge>
                  </TableCell>
                  <TableCell>
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
        </div>
      )}

      {/* Grant credits dialog */}
      <Dialog open={!!grantTarget} onOpenChange={(open) => !open && setGrantTarget(null)}>
        <DialogContent onClose={() => setGrantTarget(null)}>
          <DialogHeader>
            <DialogTitle>Grant Credits</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Granting credits to <strong>{grantTarget?.email}</strong>
            </p>
            <div className="space-y-2">
              <Label htmlFor="amount">Amount</Label>
              <Input
                id="amount"
                type="number"
                min="1"
                step="1"
                value={grantAmount}
                onChange={(e) => setGrantAmount(e.target.value)}
                placeholder="e.g. 240"
              />
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
            <Button onClick={handleGrantCredits} disabled={granting || !grantAmount}>
              {granting ? "Granting..." : "Grant Credits"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Add image dialog */}
      <Dialog open={showImageDialog} onOpenChange={setShowImageDialog}>
        <DialogContent onClose={() => setShowImageDialog(false)}>
          <DialogHeader>
            <DialogTitle>Add Workspace Image</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div className="space-y-2">
              <Label htmlFor="imgName">Display name</Label>
              <Input
                id="imgName"
                value={newImage.name}
                onChange={(e) => setNewImage((p) => ({ ...p, name: e.target.value }))}
                placeholder="GPU - PyTorch 2.x (CUDA 12)"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="imgRef">Docker image reference</Label>
              <Input
                id="imgRef"
                value={newImage.docker_ref}
                onChange={(e) => setNewImage((p) => ({ ...p, docker_ref: e.target.value }))}
                placeholder="registry.example.com/sahab-gpu:latest"
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="imgKind">Type</Label>
              <Select
                id="imgKind"
                value={newImage.kind}
                onChange={(e) => setNewImage((p) => ({ ...p, kind: e.target.value as "gpu" | "cpu" }))}
              >
                <option value="gpu">GPU</option>
                <option value="cpu">CPU</option>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowImageDialog(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSaveImage}
              disabled={savingImage || !newImage.name || !newImage.docker_ref}
            >
              {savingImage ? "Adding..." : "Add Image"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Inline rate editor component
function RateEditor({
  rate,
  onSaved,
}: {
  rate: Rate;
  onSaved: () => void;
}) {
  const [value, setValue] = useState(rate.credits_per_minute.toString());
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await admin.setRates([
        { resource_type: rate.resource_type, credits_per_minute: parseFloat(value) },
      ]);
      onSaved();
    } finally {
      setSaving(false);
    }
  };

  const label =
    rate.resource_type === "l4_gpu"
      ? "GPU session (NVIDIA L4)"
      : "CPU session";

  return (
    <div className="flex items-center gap-4">
      <div className="flex-1">
        <p className="font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">credits per minute</p>
      </div>
      <Input
        type="number"
        min="0"
        step="0.1"
        className="w-28"
        value={value}
        onChange={(e) => setValue(e.target.value)}
      />
      <Button size="sm" onClick={handleSave} disabled={saving}>
        {saving ? "Saving..." : "Save"}
      </Button>
    </div>
  );
}
