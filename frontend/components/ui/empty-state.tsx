import * as React from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * An empty state teaches the interface. "No sessions yet" tells someone nothing
 * they did not already know; the action that ends the emptiness belongs here.
 */
export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-3 rounded-md border border-dashed border-border-strong bg-card px-5 py-8",
        className
      )}
    >
      {Icon && (
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
      )}
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        {description && (
          <p className="max-w-prose text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      {action}
    </div>
  );
}
