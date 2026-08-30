"use client";

import React, { useEffect, useState } from "react";
import { LaunchForm } from "@/components/LaunchForm";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";
import { me } from "@/lib/api";
import type { User } from "@/lib/types";

export default function LaunchPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    me.get()
      .then(setUser)
      .catch(() => {
        // The authed layout redirects on an expired session.
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-prose space-y-8">
      <PageHeader
        title="Start a workspace"
        description="Choose the hardware and the environment. Most workspaces are ready in under a minute."
      />

      {loading ? (
        <div className="space-y-6">
          <Skeleton className="h-32 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      ) : (
        <LaunchForm balance={user?.credit_balance ?? 0} />
      )}
    </div>
  );
}
