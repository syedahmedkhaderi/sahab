"use client";

import * as React from "react";
import { CheckCircle2, AlertTriangle, Info, X, XCircle } from "lucide-react";
import { cn } from "@/lib/utils";

/**
 * There was no toast system at all: every outcome, success or failure, could
 * only appear as an inline alert wedged into the page, so actions that finish
 * elsewhere (stopping a session from a table row, saving a rate) reported
 * nothing.
 *
 * Toasts here report the result of an action the user just took. They are not
 * a place to put information the page should be showing.
 */

type ToastTone = "success" | "error" | "warning" | "info";

type Toast = {
  id: number;
  tone: ToastTone;
  title: string;
  description?: string;
};

type ToastInput = Omit<Toast, "id">;

const ToastContext = React.createContext<{
  toast: (input: ToastInput) => void;
} | null>(null);

const DISMISS_AFTER_MS = 6000;

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = React.useState<Toast[]>([]);
  const nextId = React.useRef(0);

  const dismiss = React.useCallback((id: number) => {
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const toast = React.useCallback(
    (input: ToastInput) => {
      const id = nextId.current++;
      setToasts((current) => [...current, { ...input, id }]);
      // Errors stay until dismissed: a message you missed is a message that
      // never happened, and a failed action is worth reading twice.
      if (input.tone !== "error") {
        window.setTimeout(() => dismiss(id), DISMISS_AFTER_MS);
      }
    },
    [dismiss]
  );

  const value = React.useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        // polite, not assertive: these follow an action the user just took, so
        // they should not interrupt what a screen reader is already saying.
        aria-live="polite"
        aria-relevant="additions"
        className="pointer-events-none fixed inset-x-0 bottom-0 z-50 flex flex-col items-center gap-2 p-4 sm:inset-x-auto sm:right-0 sm:items-end"
      >
        {toasts.map((item) => (
          <ToastCard key={item.id} toast={item} onDismiss={() => dismiss(item.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

const TONES: Record<
  ToastTone,
  { icon: typeof Info; className: string; iconClass: string }
> = {
  success: {
    icon: CheckCircle2,
    className: "border-success/30 bg-success-subtle text-success-strong",
    iconClass: "text-success",
  },
  error: {
    icon: XCircle,
    className: "border-destructive/30 bg-destructive-subtle text-destructive-strong",
    iconClass: "text-destructive",
  },
  warning: {
    icon: AlertTriangle,
    className: "border-warning/30 bg-warning-subtle text-warning-strong",
    iconClass: "text-warning",
  },
  info: {
    icon: Info,
    className: "border-border bg-card text-foreground",
    iconClass: "text-muted-foreground",
  },
};

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const { icon: Icon, className, iconClass } = TONES[toast.tone];
  return (
    <div
      className={cn(
        "pointer-events-auto flex w-full max-w-sm animate-fade-in items-start gap-2.5 rounded-md border p-3 shadow-popover",
        className
      )}
    >
      <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", iconClass)} aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm font-medium">{toast.title}</p>
        {toast.description && (
          <p className="break-words text-sm opacity-90">{toast.description}</p>
        )}
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 rounded-sm p-0.5 opacity-60 transition-opacity hover:opacity-100"
      >
        <X className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="sr-only">Dismiss</span>
      </button>
    </div>
  );
}

export function useToast() {
  const context = React.useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used inside a ToastProvider");
  }
  return context;
}
