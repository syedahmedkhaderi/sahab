import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  // Squared-off rather than a pill: this labels a state in a data table, and a
  // pill reads as a marketing tag.
  "inline-flex items-center gap-1.5 rounded-sm border px-2 py-0.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground ",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground ",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground",
        outline: "border-border text-foreground",
        // Tinted ground plus a darkened text tone from the same hue, so the
        // pair holds contrast in both themes. bg-green-100/bg-yellow-100 were
        // literal Tailwind colours outside the token system, which is why they
        // stayed light-mode green on a dark background.
        success: "border-transparent bg-success-subtle text-success-strong",
        warning: "border-transparent bg-warning-subtle text-warning-strong",
        info: "border-transparent bg-info-subtle text-info-strong",
        danger:
          "border-transparent bg-destructive-subtle text-destructive-strong",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return (
    <div className={cn(badgeVariants({ variant }), className)} {...props} />
  );
}

export { Badge, badgeVariants };
