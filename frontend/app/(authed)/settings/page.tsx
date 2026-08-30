"use client";

import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { me } from "@/lib/api";
import { ApiClientError } from "@/lib/api";
import type { User } from "@/lib/types";
import { capitalize } from "@/lib/utils";

export default function SettingsPage() {
  const { toast } = useToast();
  const [user, setUser] = useState<User | null>(null);
  const [fullName, setFullName] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    me.get()
      .then((u) => {
        setUser(u);
        setFullName(u.full_name ?? "");
      })
      .catch(() => {
        // The authed layout redirects on an expired session.
      })
      .finally(() => setLoading(false));
  }, []);

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);

    const payload: { full_name?: string; password?: string } = {};
    if (fullName !== (user?.full_name ?? "")) payload.full_name = fullName;
    if (newPassword) {
      if (newPassword !== confirmPassword) {
        setError("The two passwords do not match.");
        setSaving(false);
        return;
      }
      if (newPassword.length < 8) {
        setError("A password needs at least 8 characters.");
        setSaving(false);
        return;
      }
      payload.password = newPassword;
    }

    if (Object.keys(payload).length === 0) {
      setError("Nothing has changed yet.");
      setSaving(false);
      return;
    }

    try {
      const updated = await me.updateProfile(payload);
      setUser(updated);
      setFullName(updated.full_name ?? "");
      const changedPassword = Boolean(payload.password);
      setNewPassword("");
      setConfirmPassword("");
      toast({
        tone: "success",
        title: changedPassword ? "Password changed" : "Name updated",
        description: changedPassword
          ? "Use the new one the next time you sign in."
          : undefined,
      });
    } catch (err) {
      setError(
        err instanceof ApiClientError
          ? err.detail
          : "Could not save your changes. Please try again."
      );
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto max-w-prose space-y-8">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-prose space-y-8">
      <PageHeader
        title="Settings"
        description="Your account, and the details you can change yourself."
      />

      {/* Account facts, none of them editable here. */}
      <section className="rounded-md border border-border bg-card">
        <h2 className="border-b border-border px-5 py-3 text-sm font-medium text-foreground">
          Account
        </h2>
        <dl className="divide-y divide-border">
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Email</dt>
            <dd className="min-w-0 truncate text-sm text-foreground">
              {user?.email}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Role</dt>
            <dd className="text-sm text-foreground">
              {capitalize(user?.role ?? "student")}
            </dd>
          </div>
          <div className="flex items-center justify-between gap-4 px-5 py-3">
            <dt className="text-sm text-muted-foreground">Status</dt>
            <dd>
              <Badge variant={user?.status === "active" ? "success" : "warning"}>
                {capitalize(user?.status ?? "pending")}
              </Badge>
            </dd>
          </div>
        </dl>
        <p className="border-t border-border px-5 py-3 text-xs text-muted-foreground">
          Your email address and role are set by an administrator and cannot be
          changed here.
        </p>
      </section>

      <form
        onSubmit={handleProfileSave}
        className="space-y-5 rounded-md border border-border bg-card p-5"
      >
        <div>
          <h2 className="text-sm font-medium text-foreground">Profile</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Leave the password fields empty to keep your current password.
          </p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="fullName">Full name</Label>
          <Input
            id="fullName"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            autoComplete="name"
          />
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="newPassword">New password</Label>
          <Input
            id="newPassword"
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            autoComplete="new-password"
            minLength={8}
          />
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="confirmPassword">Repeat the new password</Label>
          <Input
            id="confirmPassword"
            type="password"
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            autoComplete="new-password"
          />
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" loading={saving}>
          {saving ? "Saving" : "Save changes"}
        </Button>
      </form>
    </div>
  );
}
