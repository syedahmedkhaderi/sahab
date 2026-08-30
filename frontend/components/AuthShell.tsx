import * as React from "react";
import Link from "next/link";
import { Wordmark } from "@/components/Wordmark";

/**
 * The frame around every page you can reach without an account. Login, signup
 * and verify each built their own centred card and their own logo block, at
 * slightly different sizes.
 */
export function AuthShell({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: React.ReactNode;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col bg-background px-4 py-10 sm:py-16">
      <div className="mx-auto w-full max-w-form">
        <Link href="/" className="inline-block rounded-sm">
          <Wordmark showSubtitle />
        </Link>

        <div className="mt-8 rounded-md border border-border bg-card p-6">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            {title}
          </h1>
          {description && (
            <p className="mt-1.5 text-sm text-muted-foreground">{description}</p>
          )}
          <div className="mt-6">{children}</div>
        </div>

        {footer && (
          <div className="mt-4 text-sm text-muted-foreground">{footer}</div>
        )}
      </div>
    </div>
  );
}
