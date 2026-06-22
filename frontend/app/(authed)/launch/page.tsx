"use client";

import React, { useEffect, useState } from "react";
import { LaunchForm } from "@/components/LaunchForm";
import { me } from "@/lib/api";
import type { User } from "@/lib/types";

export default function LaunchPage() {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    me.get()
      .then(setUser)
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Launch Workspace</h1>
        <p className="mt-1 text-muted-foreground">
          Pick a runtime and environment. Your workspace will be ready in under a minute.
        </p>
      </div>

      {loading ? (
        <div className="flex h-48 items-center justify-center text-muted-foreground">
          Loading...
        </div>
      ) : (
        <LaunchForm balance={user?.credit_balance ?? 0} />
      )}
    </div>
  );
}
