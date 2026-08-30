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
  fullBleed = false,
}: {
  children: React.ReactNode;
  className?: string;
  /**
   * Run the bar edge to edge instead of centring it on the content column.
   * The workspace shell sits above a full-width iframe, where a centred bar
   * would leave the controls floating in the middle of the screen.
   */
  fullBleed?: boolean;
}) {
  return (
    <header
      className={cn(
        "sticky top-0 z-40 border-b border-border bg-background/90 backdrop-blur-sm supports-[backdrop-filter]:bg-background/75",
        className
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center justify-between gap-4 px-4 sm:px-6 lg:px-8",
          fullBleed ? "w-full" : "mx-auto max-w-content"
        )}
      >
        {children}
      </div>
    </header>
  );
}
