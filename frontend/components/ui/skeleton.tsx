import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * Loading placeholders that keep the page's shape, rather than a spinner in the
 * middle of an empty container. The sweep is one authored moment, not a pulse
 * on every element.
 */
export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "relative overflow-hidden rounded-sm bg-muted",
        "after:absolute after:inset-0 after:-translate-x-full after:animate-shimmer",
        "after:bg-gradient-to-r after:from-transparent after:via-card/60 after:to-transparent",
        className
      )}
    />
  );
}
