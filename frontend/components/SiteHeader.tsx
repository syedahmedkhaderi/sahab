import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The sticky header shell. The exact
 * `bg-background/95 backdrop-blur supports-[backdrop-filter]:…` string was
 * duplicated between the landing page and Nav, so the two headers could drift
 * apart without anyone noticing.
 */
export function SiteHeader({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur-sm supports-[backdrop-filter]:bg-background/75",
        className
      )}
    >
      <div className="mx-auto flex h-14 max-w-content items-center justify-between gap-4 px-4 sm:px-6 lg:px-8">
        {children}
      </div>
    </header>
  );
}
