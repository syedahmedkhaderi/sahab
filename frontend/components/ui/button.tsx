import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";
import { Spinner } from "@/components/ui/spinner";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        // hover:bg-primary/90 fades the blue toward the page rather than
        // deepening it. --primary-hover is the deliberate darker step.
        default:
          "bg-primary text-primary-foreground hover:bg-primary-hover active:bg-primary-hover",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive-strong",
        outline:
          "border border-border-strong bg-card text-foreground hover:bg-accent",
        secondary:
          "bg-secondary text-secondary-foreground hover:bg-accent",
        ghost: "text-foreground hover:bg-accent",
        link: "text-primary underline underline-offset-4 decoration-primary/30 hover:decoration-primary",
      },
      size: {
        default: "h-9 px-3.5",
        sm: "h-8 px-3 text-xs",
        lg: "h-10 px-5",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  /** Render the single child element with button styling instead of a <button>. */
  asChild?: boolean;
  /** Shows a spinner and blocks further presses while a request is in flight. */
  loading?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    { className, variant, size, loading, children, disabled, asChild, ...props },
    ref
  ) => {
    // `asChild` was declared here but never implemented, so passing it rendered
    // a plain button and leaked an unknown `asChild` attribute to the DOM. It
    // exists so a link can carry button styling without nesting an <a> in a
    // <button>, which is invalid markup and breaks keyboard activation.
    if (asChild && React.isValidElement(children)) {
      const child = children as React.ReactElement<{ className?: string }>;
      return React.cloneElement(child, {
        ...props,
        className: cn(buttonVariants({ variant, size, className }), child.props.className),
      } as React.HTMLAttributes<HTMLElement>);
    }

    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        // A button mid-request must not be pressable again, and a screen reader
        // should hear that it is working rather than silence.
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {loading && <Spinner className="h-3.5 w-3.5" />}
        {children}
      </button>
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
