import * as React from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * The one spinner. A raw <Loader2 className="animate-spin"> was inlined in five
 * places at four different sizes, which is how a design system starts to drift.
 */
export function Spinner({
  className,
  label = "Loading",
}: {
  className?: string;
  label?: string;
}) {
  return (
    <>
      <Loader2
        aria-hidden="true"
        className={cn("h-4 w-4 shrink-0 animate-spin", className)}
      />
      <span className="sr-only">{label}</span>
    </>
  );
}
