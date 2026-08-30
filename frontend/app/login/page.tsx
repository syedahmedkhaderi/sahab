"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AuthShell } from "@/components/AuthShell";
import { auth } from "@/lib/api";
import { ApiClientError } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  // ?from= is appended both by the middleware, when it bounces someone off a
  // protected page, and by /api/oauth/authorize when the hub handoff finds no
  // session. Either way the user resumes where they were going.
  const from = searchParams.get("from");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await auth.login({ email, password });
      const target = from && from.startsWith("/") ? from : "/dashboard";
      if (target.startsWith("/api/")) {
        // An API route, not a Next page: the OAuth handoff resuming. The Next
        // router cannot resolve it, so this has to be a real navigation.
        window.location.assign(target);
      } else {
        router.push(target);
      }
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.detail);
      } else {
        setError("Could not reach the server. Check your connection and try again.");
      }
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-1.5">
        <Label htmlFor="email">University email</Label>
        <Input
          id="email"
          type="email"
          placeholder="you@udst.edu.qa"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          required
          autoComplete="email"
          autoFocus
        />
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="password">Password</Label>
        <Input
          id="password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />
      </div>

      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      <Button type="submit" className="w-full" loading={loading}>
        {loading ? "Signing in" : "Sign in"}
      </Button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <AuthShell
      title="Sign in"
      description="Use the UDST address your account was created with."
      footer={
        <>
          No account yet?{" "}
          <Link
            href="/signup"
            className="font-medium text-primary underline underline-offset-4"
          >
            Request one
          </Link>
          .
        </>
      }
    >
      <Suspense fallback={<div className="h-56" />}>
        <LoginForm />
      </Suspense>
    </AuthShell>
  );
}
