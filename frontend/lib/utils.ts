import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format credits to a readable number with up to 1 decimal place. */
export function formatCredits(n: number): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 1,
  });
}

/** Format ISO timestamp to local date + time string. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** Return elapsed minutes between two ISO timestamps (or now). */
export function elapsedMinutes(from: string, to?: string): number {
  const start = new Date(from).getTime();
  const end = to ? new Date(to).getTime() : Date.now();
  return Math.floor((end - start) / 60_000);
}

/** Human-readable duration from minutes. */
export function formatDuration(minutes: number): string {
  // A session that ran for forty seconds is not "0m" — that reads as though
  // nothing happened.
  if (minutes < 1) return "<1m";
  if (minutes < 60) return `${minutes}m`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h}h` : `${h}h ${m}m`;
}

/** "1 credit", "2.5 credits" — the unit agrees with the number. */
export function creditsWithUnit(n: number): string {
  return `${formatCredits(n)} ${n === 1 ? "credit" : "credits"}`;
}

/**
 * VRAM as the vendor states it. nvidia-smi reports MiB (23034 for an L4), so
 * dividing by 1024 gives 22 and contradicts every other mention of "24 GB".
 * GPU capacity is quoted in decimal GB, which is where 24 comes from.
 */
export function formatVram(mib: number): string {
  return `${Math.round((mib * 1024 * 1024) / 1e9)} GB`;
}

/** Capitalize first letter. */
export function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}
