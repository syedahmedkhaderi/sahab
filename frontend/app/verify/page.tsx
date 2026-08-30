"use client";

import React, { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { AuthShell } from "@/components/AuthShell";
import { auth } from "@/lib/api";
import { ApiClientError } from "@/lib/api";

function VerifyContent() {
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage(
        "This page needs a verification token in the link, and there is not one here."
      );
      return;
    }

    auth
      .verify({ token })
      .then(() => {
        setStatus("success");
        setMessage("Your address is confirmed. You can sign in now.");
      })
      .catch((err) => {
        setStatus("error");
        setMessage(
          err instanceof ApiClientError
            ? err.detail
            : "That link could not be verified. It may have already been used."
        );
      });
  }, [token]);

  if (status === "loading") {
    return (
      <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
        <Spinner label="Checking your link" />
        Checking your link
      </div>
    );
  }

  const isSuccess = status === "success";

  return (
    <div className="space-y-4">
      <div className="flex items-start gap-2.5">
        {isSuccess ? (
          <CheckCircle2
            className="mt-0.5 h-4 w-4 shrink-0 text-success"
            aria-hidden="true"
          />
        ) : (
          <XCircle
            className="mt-0.5 h-4 w-4 shrink-0 text-destructive"
            aria-hidden="true"
          />
        )}
        <p className="text-sm text-muted-foreground">{message}</p>
      </div>
      <Button variant={isSuccess ? "default" : "outline"} asChild>
        <Link href={isSuccess ? "/login" : "/signup"}>
          {isSuccess ? "Sign in" : "Back to the request form"}
        </Link>
      </Button>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <AuthShell title="Confirming your address">
      <Suspense
        fallback={
          <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
            <Spinner />
            Loading
          </div>
        }
      >
        <VerifyContent />
      </Suspense>
    </AuthShell>
  );
}
