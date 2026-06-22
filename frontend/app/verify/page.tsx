"use client";

import React, { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { CheckCircle, XCircle, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { auth } from "@/lib/api";
import { ApiClientError } from "@/lib/api";

// useSearchParams must be inside a Suspense boundary in Next.js 14 App Router.
function VerifyContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");

  const [status, setStatus] = useState<"loading" | "success" | "error">("loading");
  const [message, setMessage] = useState("");

  useEffect(() => {
    if (!token) {
      setStatus("error");
      setMessage("No verification token found. Please check your email link.");
      return;
    }

    auth
      .verify({ token })
      .then(() => {
        setStatus("success");
        setMessage("Your email has been verified. You can now sign in.");
      })
      .catch((err) => {
        setStatus("error");
        if (err instanceof ApiClientError) {
          setMessage(err.detail);
        } else {
          setMessage("Verification failed. The link may have expired.");
        }
      });
  }, [token]);

  return (
    <div className="flex flex-col items-center gap-4 text-center">
      {status === "loading" && (
        <>
          <Loader2 className="h-12 w-12 animate-spin text-primary" />
          <h2 className="text-xl font-semibold">Verifying your email...</h2>
        </>
      )}
      {status === "success" && (
        <>
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
            <CheckCircle className="h-6 w-6 text-green-700" />
          </div>
          <h2 className="text-xl font-semibold">Email verified</h2>
          <p className="text-muted-foreground">{message}</p>
          <Button onClick={() => router.push("/login")}>Sign in</Button>
        </>
      )}
      {status === "error" && (
        <>
          <div className="flex h-12 w-12 items-center justify-center rounded-full bg-red-100">
            <XCircle className="h-6 w-6 text-red-700" />
          </div>
          <h2 className="text-xl font-semibold">Verification failed</h2>
          <p className="text-muted-foreground">{message}</p>
          <Button variant="outline" onClick={() => router.push("/signup")}>
            Back to sign up
          </Button>
        </>
      )}
    </div>
  );
}

export default function VerifyPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-4">
      <div className="w-full max-w-md">
        <Card>
          <CardContent className="pt-6">
            <Suspense
              fallback={
                <div className="flex flex-col items-center gap-4 text-center">
                  <Loader2 className="h-12 w-12 animate-spin text-primary" />
                  <h2 className="text-xl font-semibold">Loading...</h2>
                </div>
              }
            >
              <VerifyContent />
            </Suspense>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
