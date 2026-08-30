"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Nav } from "@/components/Nav";
import { ToastProvider } from "@/components/ui/toast";
import { Skeleton } from "@/components/ui/skeleton";
import { me } from "@/lib/api";
import type { User } from "@/lib/types";

export default function AuthedLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    me.get()
      .then(setUser)
      .catch(() => {
        router.replace("/login");
      })
      .finally(() => setLoading(false));
  }, [router]);

  // Hold the page's shape while the user loads, rather than a spinner in the
  // middle of an empty screen — the layout does not jump when content lands.
  if (loading) {
    return (
      <div className="min-h-screen bg-background">
        <div className="h-14 border-b border-border" />
        <div className="mx-auto max-w-content space-y-6 px-4 py-8 sm:px-6 lg:px-8">
          <Skeleton className="h-8 w-48" />
          <Skeleton className="h-36 w-full" />
        </div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <ToastProvider>
      <div className="min-h-screen bg-background">
        <Nav user={user} />
        <main className="mx-auto max-w-content px-4 py-8 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </ToastProvider>
  );
}
