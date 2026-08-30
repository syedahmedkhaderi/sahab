"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { AuthShell } from "@/components/AuthShell";
import { auth } from "@/lib/api";
import { ApiClientError } from "@/lib/api";

const allowedDomain = process.env.NEXT_PUBLIC_ALLOWED_DOMAIN ?? "udst.edu.qa";

export default function SignupPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);

    try {
      await auth.signup({ email, full_name: fullName, password });
      setSubmitted(true);
    } catch (err) {
      if (err instanceof ApiClientError) {
        setError(err.detail);
      } else {
        setError("Could not reach the server. Check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  };

  if (submitted) {
    // No email is sent anywhere. This screen used to say "we sent a
    // verification link — click it to activate your account", which described
    // a flow that does not exist and left people waiting for a message that
    // was never coming. Approval is a person, so the screen says so.
    return (
      <AuthShell
        title="Your account is waiting for approval"
        description={
          <>
            The request for <span className="text-foreground">{email}</span> has
            been recorded.
          </>
        }
        footer={
          <>
            Once it is approved you can{" "}
            <Link
              href="/login"
              className="font-medium text-primary underline underline-offset-4"
            >
              sign in
            </Link>
            .
          </>
        }
      >
        <div className="space-y-4 text-sm text-muted-foreground">
          <p>
            A platform administrator reviews new accounts by hand and grants the
            credits that go with them. There is no confirmation email. Nothing
            will arrive in your inbox, so there is nothing to wait for.
          </p>
          <p>
            If you need access for a class or a deadline, tell the administrator
            directly rather than waiting.
          </p>
        </div>
      </AuthShell>
    );
  }

  return (
    <AuthShell
      title="Request an account"
      description={`Open to ${allowedDomain} addresses. An administrator approves each one before it can launch anything.`}
      footer={
        <>
          Already have an account?{" "}
          <Link
            href="/login"
            className="font-medium text-primary underline underline-offset-4"
          >
            Sign in
          </Link>
          .
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="fullName">Full name</Label>
          <Input
            id="fullName"
            type="text"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
            required
            autoComplete="name"
            autoFocus
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="email">University email</Label>
          <Input
            id="email"
            type="email"
            placeholder={`you@${allowedDomain}`}
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
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
            autoComplete="new-password"
            minLength={8}
          />
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <Button type="submit" className="w-full" loading={loading}>
          {loading ? "Sending your request" : "Request an account"}
        </Button>
      </form>
    </AuthShell>
  );
}
