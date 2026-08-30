import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The Sahab lockup: a white cloud and the wordmark on a UDST-blue block.
 *
 * The word SAHAB lives inside the graphic, so there is deliberately no adjacent
 * HTML wordmark — rendering both would show the name twice. That also means the
 * <svg> carries the accessible name, since there is no longer any text beside
 * it to name the link that usually wraps this.
 *
 * The <text> element sets no font-family on purpose. Inline SVG inherits it
 * through the normal CSS cascade, so it picks up Inter from `body.font-sans`.
 * Naming "Inter" explicitly would silently fall back to Helvetica, because
 * next/font generates a hashed family name rather than that literal string.
 */
export function Wordmark({
  className,
  showSubtitle = false,
}: {
  className?: string;
  showSubtitle?: boolean;
}) {
  return (
    <span className={cn("flex flex-col", className)}>
      <svg
        viewBox="0 0 500 200"
        role="img"
        aria-label="Sahab"
        className="h-7 w-[70px] shrink-0"
      >
        {/* Literal blue, not the --primary token: this block is a fixed brand
            asset and must read the same in both themes. It is a hair off the
            token's #0055B8, which is imperceptible and not worth shifting every
            button, ring and link in the product to reconcile. */}
        <rect width="500" height="200" rx="16" fill="#0558b6" />
        <g transform="translate(70, 50)">
          <path
            d="M 45 90
               A 25 25 0 0 1 50 45
               A 35 35 0 0 1 115 35
               A 25 25 0 0 1 150 55
               A 20 20 0 0 1 150 90
               Z"
            fill="#ffffff"
          />
        </g>
        <text
          x="245"
          y="125"
          fontSize="58"
          fontWeight="800"
          letterSpacing="3"
          fill="#ffffff"
        >
          SAHAB
        </text>
      </svg>
      {showSubtitle && (
        <span className="mt-2 text-xs text-muted-foreground">
          University of Doha for Science and Technology
        </span>
      )}
    </span>
  );
}
