"use client";

import React, { useEffect, useRef, useState } from "react";
import { Check, Copy, Loader2, Terminal, KeyRound } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { admin, ApiClientError } from "@/lib/api";
import type { GpuNode, NodeCreateResponse } from "@/lib/types";

type Mode = "command" | "ssh";

interface AddNodeDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Called whenever the node list may have changed, so the table can refresh. */
  onChanged: () => void;
}

/**
 * Adds a GPU server to the pool, two ways.
 *
 * Both run the identical join script — the difference is only who types it. The
 * "command" path hands the admin a line to paste on the machine; the "SSH" path
 * has the control plane run that same line over SSH. Keeping them the same
 * script means a failure in one is reproducible in the other.
 */
export function AddNodeDialog({ open, onOpenChange, onChanged }: AddNodeDialogProps) {
  const [mode, setMode] = useState<Mode>("command");
  const [displayName, setDisplayName] = useState("");
  const [address, setAddress] = useState("");

  const [sshPort, setSshPort] = useState("22");
  const [sshUser, setSshUser] = useState("");
  const [sshSecret, setSshSecret] = useState("");
  const [authKind, setAuthKind] = useState<"password" | "key">("password");
  const [vpnKey, setVpnKey] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<NodeCreateResponse | null>(null);
  const [copied, setCopied] = useState(false);

  // Populated once an SSH install is running, and polled until it finishes.
  const [installNode, setInstallNode] = useState<GpuNode | null>(null);
  const [installLog, setInstallLog] = useState("");
  const [installStatus, setInstallStatus] = useState<string>("");
  const logRef = useRef<HTMLPreElement>(null);

  const reset = () => {
    setMode("command");
    setDisplayName("");
    setAddress("");
    setSshPort("22");
    setSshUser("");
    setSshSecret("");
    setAuthKind("password");
    setVpnKey("");
    setError(null);
    setCreated(null);
    setCopied(false);
    setInstallNode(null);
    setInstallLog("");
    setInstallStatus("");
  };

  const close = () => {
    reset();
    onOpenChange(false);
  };

  // Follow a running install. Polling rather than streaming: the install takes
  // minutes and a dropped connection mid-install should not lose the log.
  useEffect(() => {
    if (!installNode) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const result = await admin.nodeInstallLog(installNode.id);
        if (cancelled) return;
        setInstallLog(result.log);
        setInstallStatus(result.status);
        if (result.status === "completed" || result.status === "failed") {
          onChanged();
        }
      } catch {
        // A single failed poll is not worth reporting; the next one retries.
      }
    };

    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [installNode, onChanged]);

  // Keep the newest output in view without stealing the scroll if the admin has
  // deliberately scrolled up to read something.
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    if (atBottom) el.scrollTop = el.scrollHeight;
  }, [installLog]);

  const describeError = (e: unknown) =>
    e instanceof ApiClientError
      ? e.detail
      : e instanceof Error
        ? e.message
        : "Something went wrong.";

  const handleCreate = async () => {
    setBusy(true);
    setError(null);
    try {
      const result = await admin.createNode({
        display_name: displayName || undefined,
        address: address || undefined,
        name: address || displayName || undefined,
        ...(mode === "ssh"
          ? {
              ssh_host: address || undefined,
              ssh_port: Number(sshPort) || 22,
              ssh_user: sshUser || undefined,
              ...(authKind === "key"
                ? { ssh_private_key: sshSecret }
                : { ssh_password: sshSecret }),
            }
          : {}),
      });
      setCreated(result);
      onChanged();

      if (mode === "ssh") {
        await admin.installNode(result.node.id, {
          vpn_auth_key: vpnKey || undefined,
        });
        setInstallNode(result.node);
        setInstallStatus("running");
      }
    } catch (e) {
      setError(describeError(e));
    } finally {
      setBusy(false);
    }
  };

  const copyCommand = async () => {
    if (!created) return;
    try {
      await navigator.clipboard.writeText(created.join_command);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      setError("Could not copy — select the command and copy it by hand.");
    }
  };

  const canCreate =
    mode === "command"
      ? address.trim().length > 0 || displayName.trim().length > 0
      : address.trim().length > 0 && sshUser.trim().length > 0 && sshSecret.length > 0;

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-2xl" onClose={close}>
        <DialogHeader>
          <DialogTitle>Add a GPU server</DialogTitle>
        </DialogHeader>

        {/* --- the command to paste, once the machine is registered --------- */}
        {created && mode === "command" ? (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              Run this on <span className="font-medium text-foreground">{created.node.display_name ?? created.node.name}</span>.
              It installs everything the machine needs and adds its GPUs to the
              pool. It takes about ten minutes.
            </p>

            <div className="rounded-md border border-border bg-muted/40 p-3">
              <pre className="overflow-x-auto whitespace-pre-wrap break-all font-mono text-xs text-foreground">
                {created.join_command}
              </pre>
            </div>

            <div className="flex items-center gap-2">
              <Button size="sm" variant="outline" onClick={copyCommand}>
                {copied ? (
                  <Check className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <Copy className="h-4 w-4" aria-hidden="true" />
                )}
                {copied ? "Copied" : "Copy command"}
              </Button>
              <span className="text-xs text-muted-foreground">
                Single use, expires in 24 hours.
              </span>
            </div>

            <Alert>
              <AlertDescription>
                The token in that command is shown once and is not stored, so
                copy it now. If you lose it, delete the machine and add it again.
              </AlertDescription>
            </Alert>

            <p className="text-sm text-muted-foreground">
              The machine appears in the list as{" "}
              <span className="font-medium text-foreground">Enrolling</span>, then{" "}
              <span className="font-medium text-foreground">Ready</span> once its
              GPUs are in the pool.
            </p>
          </div>
        ) : installNode ? (
          /* --- SSH install log ------------------------------------------- */
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              Installing on{" "}
              <span className="font-mono text-foreground">{installNode.ssh_user}@{installNode.ssh_host}</span>.
              This takes several minutes; you can close this and come back to it.
            </p>
            <pre
              ref={logRef}
              className="h-72 overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed text-muted-foreground"
            >
              {installLog || "Connecting…"}
            </pre>
            {installStatus === "failed" && (
              <Alert variant="destructive">
                <AlertDescription>
                  The install did not finish. The output above says why — fix it
                  and add the machine again.
                </AlertDescription>
              </Alert>
            )}
            {installStatus === "completed" && (
              <Alert>
                <AlertDescription>
                  Finished. The machine should show as Ready in the list.
                </AlertDescription>
              </Alert>
            )}
          </div>
        ) : (
          /* --- the form --------------------------------------------------- */
          <div className="space-y-4">
            {/* Two-state toggle buttons, not role="tab". The tab role promises a
                matching tabpanel with aria-controls; without one a screen reader
                announces a tab and then finds nothing to move into. aria-pressed
                says exactly what this is: a pair of buttons, one of them on. */}
            <div className="flex gap-2" role="group" aria-label="How to add the machine">
              <Button
                type="button"
                aria-pressed={mode === "command"}
                variant={mode === "command" ? "default" : "outline"}
                size="sm"
                onClick={() => setMode("command")}
              >
                <Terminal className="h-4 w-4" aria-hidden="true" />
                Give me a command
              </Button>
              <Button
                type="button"
                aria-pressed={mode === "ssh"}
                variant={mode === "ssh" ? "default" : "outline"}
                size="sm"
                onClick={() => setMode("ssh")}
              >
                <KeyRound className="h-4 w-4" aria-hidden="true" />
                Install over SSH
              </Button>
            </div>

            <p className="text-sm text-muted-foreground">
              {mode === "command"
                ? "You get a single command to run on the machine. Nothing is stored here except the machine's name."
                : "Sahab connects to the machine and runs the install itself. The login is saved (encrypted) so upgrades can be re-run from here later."}
            </p>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="node-address">
                  {mode === "ssh" ? "IP address" : "IP address (optional)"}
                </Label>
                <Input
                  id="node-address"
                  placeholder="10.125.81.53"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="node-name">Label (optional)</Label>
                <Input
                  id="node-name"
                  placeholder="Lab GPU server 2"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>
            </div>

            {mode === "ssh" && (
              <>
                <div className="grid gap-4 sm:grid-cols-2">
                  <div className="space-y-1.5">
                    <Label htmlFor="ssh-user">SSH username</Label>
                    <Input
                      id="ssh-user"
                      autoComplete="off"
                      placeholder="ubuntu"
                      value={sshUser}
                      onChange={(e) => setSshUser(e.target.value)}
                    />
                  </div>
                  <div className="space-y-1.5">
                    <Label htmlFor="ssh-port">SSH port</Label>
                    <Input
                      id="ssh-port"
                      inputMode="numeric"
                      value={sshPort}
                      onChange={(e) => setSshPort(e.target.value)}
                    />
                  </div>
                </div>

                <div className="flex gap-2" role="group" aria-label="Credential type">
                  <Button
                    type="button"
                    aria-pressed={authKind === "password"}
                    variant={authKind === "password" ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => setAuthKind("password")}
                  >
                    Password
                  </Button>
                  <Button
                    type="button"
                    aria-pressed={authKind === "key"}
                    variant={authKind === "key" ? "secondary" : "outline"}
                    size="sm"
                    onClick={() => setAuthKind("key")}
                  >
                    Private key
                  </Button>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="ssh-secret">
                    {authKind === "password" ? "SSH password" : "Private key (PEM)"}
                  </Label>
                  {authKind === "password" ? (
                    <Input
                      id="ssh-secret"
                      type="password"
                      autoComplete="new-password"
                      value={sshSecret}
                      onChange={(e) => setSshSecret(e.target.value)}
                    />
                  ) : (
                    <textarea
                      id="ssh-secret"
                      rows={5}
                      className="flex w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-xs ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                      value={sshSecret}
                      onChange={(e) => setSshSecret(e.target.value)}
                    />
                  )}
                  <p className="text-xs text-muted-foreground">
                    The account needs sudo. Stored encrypted; never shown again.
                  </p>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="vpn-key">Tailscale auth key (optional)</Label>
                  <Input
                    id="vpn-key"
                    autoComplete="off"
                    placeholder="tskey-auth-…"
                    value={vpnKey}
                    onChange={(e) => setVpnKey(e.target.value)}
                  />
                  <p className="text-xs text-muted-foreground">
                    Only for a machine that is not on the same network as this
                    one. Leave blank on the university network.
                  </p>
                </div>
              </>
            )}

            {error && (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            )}
          </div>
        )}

        <DialogFooter>
          {created || installNode ? (
            <Button onClick={close}>Done</Button>
          ) : (
            <>
              <Button variant="outline" onClick={close} disabled={busy}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={!canCreate || busy}>
                {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />}
                {mode === "command" ? "Get the command" : "Install now"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
