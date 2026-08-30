import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The Sahab lockup: a blue tile holding the cloud, with the name beside it.
 *
 * The blue block wraps the cloud only, not the whole lockup. A square tile has
 * no side padding to get wrong, which is what went wrong before: the previous
 * single-block mark carried 70 units of inset on the left and 31 on the right,
 * and read as a chip rather than a brand.
 *
 * The name is HTML, not an SVG <text> element. That gives it real Inter with
 * real kerning at every size, and `currentColor`, so it stays legible on any
 * background including dark. An SVG <text> could not even name Inter, because
 * next/font generates a hashed family name rather than that literal string.
 *
 * Because the name is now text beside the graphic, the <svg> is decorative and
 * the <span> supplies the accessible name for the <Link> that usually wraps
 * this. (The previous version was the other way round.)
 */

const SIZES = {
  md: { tile: "h-8 w-8", word: "text-lg", gap: "gap-2.5" },
  lg: { tile: "h-11 w-11", word: "text-2xl", gap: "gap-3" },
} as const;

export function Wordmark({
  className,
  size = "md",
  showSubtitle = false,
}: {
  className?: string;
  size?: keyof typeof SIZES;
  showSubtitle?: boolean;
}) {
  const s = SIZES[size];

  return (
    <span className={cn("inline-flex flex-col", className)}>
      <span className={cn("inline-flex items-center", s.gap)}>
        <svg
          viewBox="0 0 100 100"
          aria-hidden="true"
          className={cn("shrink-0", s.tile)}
        >
          {/* Literal blue, not the --primary token: this tile is a fixed brand
              asset and must read the same in both themes. It is a hair off the
              token's #0055B8, which is imperceptible and not worth shifting
              every button, ring and link in the product to reconcile. */}
          <rect width="100" height="100" rx="22" fill="#0558b6" />
          {/* Three lobes over a rounded base, all one fill so the overlaps
              disappear. Drawn as primitives rather than a single union path so
              the proportions stay adjustable.

              The base bar's ends are flush with the outer lobes (both at x=22
              and x=78), which is what keeps the silhouette clean instead of
              lumpy. The bounding box is x 22-78, y 28.5-67: narrow enough to
              clear the tile's 22-unit corner radius, and sitting a little above
              the geometric centre because the mass is bottom-weighted, so it
              reads as centred. Checked by rendering at 16/24/32/64/128px. */}
          <g fill="#ffffff">
            <circle cx="52" cy="46" r="17.5" />
            <circle cx="34" cy="54" r="12" />
            <circle cx="67" cy="55" r="11" />
            <rect x="22" y="54" width="56" height="13" rx="6.5" />
          </g>
        </svg>
        <span className={cn("font-semibold tracking-tight", s.word)}>
          Sahab
        </span>
      </span>
      {showSubtitle && (
        <span className="mt-2 text-xs text-muted-foreground">
          University of Doha for Science and Technology
        </span>
      )}
    </span>
  );
}
