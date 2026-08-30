"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * The admin console hand-rolled a pill bar out of buttons and a border. This is
 * the same navigation as a real tablist: arrow keys move between tabs, the
 * selected one is announced, and the underline marks position rather than
 * painting a filled pill that competes with the primary action.
 */
export type TabItem<T extends string = string> = {
  id: T;
  label: string;
  icon?: React.ReactNode;
  /** Optional count shown after the label, e.g. a number of queued sessions. */
  badge?: React.ReactNode;
};

export function Tabs<T extends string>({
  items,
  value,
  onValueChange,
  className,
  label,
}: {
  items: readonly TabItem<T>[];
  value: T;
  onValueChange: (value: T) => void;
  className?: string;
  label: string;
}) {
  const refs = React.useRef<Record<string, HTMLButtonElement | null>>({});

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = items.findIndex((item) => item.id === value);
    if (index < 0) return;

    let next = index;
    if (event.key === "ArrowRight") next = (index + 1) % items.length;
    else if (event.key === "ArrowLeft") next = (index - 1 + items.length) % items.length;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = items.length - 1;
    else return;

    event.preventDefault();
    const target = items[next];
    onValueChange(target.id);
    refs.current[target.id]?.focus();
  };

  return (
    <div
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn(
        "flex gap-1 overflow-x-auto border-b border-border",
        className
      )}
    >
      {items.map((item) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(node) => {
              refs.current[item.id] = node;
            }}
            role="tab"
            type="button"
            id={`tab-${item.id}`}
            aria-selected={selected}
            aria-controls={`panel-${item.id}`}
            tabIndex={selected ? 0 : -1}
            onClick={() => onValueChange(item.id)}
            className={cn(
              "-mb-px flex shrink-0 items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition-colors",
              selected
                ? "border-primary text-foreground"
                : "border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground"
            )}
          >
            {item.icon}
            {item.label}
            {item.badge != null && (
              <span className="ml-0.5 rounded-sm bg-muted px-1.5 py-0.5 font-mono text-xs text-muted-foreground">
                {item.badge}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({
  id,
  active,
  children,
}: {
  id: string;
  active: boolean;
  children: React.ReactNode;
}) {
  if (!active) return null;
  return (
    <div
      role="tabpanel"
      id={`panel-${id}`}
      aria-labelledby={`tab-${id}`}
      tabIndex={0}
      className="animate-fade-in focus-visible:outline-none"
    >
      {children}
    </div>
  );
}
