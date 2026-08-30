import * as React from "react";
import { cn } from "@/lib/utils";

const siteName = process.env.NEXT_PUBLIC_SITE_NAME ?? "Sahab";

/**
 * Sahab's mark. Two stacked bars in the UDST blue: the two L4s this platform
 * actually has. Drawn rather than borrowed — there is no UDST logo asset in the
 * repository, and Sahab presents as its own product in the university's colours
 * rather than as an official university system.
 */
export function Wordmark({
  className,
  showSubtitle = false,
}: {
  className?: string;
  showSubtitle?: boolean;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <svg
        viewBox="0 0 20 20"
        aria-hidden="true"
        className="h-5 w-5 shrink-0 text-primary"
        fill="none"
      >
        <rect
          x="1.5"
          y="3.5"
          width="17"
          height="5.5"
          rx="1.5"
          stroke="currentColor"
          strokeWidth="1.75"
        />
        <rect
          x="1.5"
          y="11"
          width="17"
          height="5.5"
          rx="1.5"
          stroke="currentColor"
          strokeWidth="1.75"
        />
        <circle cx="5.25" cy="6.25" r="1" fill="currentColor" />
        <circle cx="5.25" cy="13.75" r="1" fill="currentColor" />
      </svg>
      <span className="flex flex-col leading-none">
        <span className="text-[0.9375rem] font-semibold tracking-tight text-foreground">
          {siteName}
        </span>
        {showSubtitle && (
          <span className="mt-1 text-xs text-muted-foreground">
            University of Doha for Science and Technology
          </span>
        )}
      </span>
    </span>
  );
}
