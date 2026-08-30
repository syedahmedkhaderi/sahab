// ---------------------------------------------------------
// Core domain types — mirror the backend PostgreSQL schema
// ---------------------------------------------------------

export type UserRole = "student" | "researcher" | "professor" | "admin";
export type UserStatus = "pending" | "active" | "disabled";

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  role: UserRole;
  status: UserStatus;
  credit_balance: number;
  created_at: string;
}

// ---------------------------------------------------------
// GPU inventory
// ---------------------------------------------------------

export type GpuStatus = "free" | "leased" | "disabled";

export interface GpuInventory {
  id: string;
  gpu_uuid: string;
  model: string;
  vram_mb: number;
  status: GpuStatus;
}

// ---------------------------------------------------------
// Workspace images
// ---------------------------------------------------------

export type ImageKind = "gpu" | "cpu";

export interface Image {
  id: string;
  name: string;
  docker_ref: string;
  kind: ImageKind;
  is_default: boolean;
  enabled: boolean;
}

// ---------------------------------------------------------
// Pricing rates
// ---------------------------------------------------------

export type ResourceType = "l4_gpu" | "cpu";

export interface Rate {
  id: string;
  resource_type: ResourceType;
  credits_per_minute: number;
}

// ---------------------------------------------------------
// Sessions
// ---------------------------------------------------------

export type SessionState =
  | "requested"
  | "queued"
  | "starting"
  | "running"
  | "stopping"
  | "stopped"
  | "failed";

export interface Session {
  id: string;
  user_id: string;
  image_id: string;
  resource_type: ResourceType;
  state: SessionState;
  queue_pos: number | null;
  started_at: string | null;
  ended_at: string | null;
  last_metered_at: string | null;
  created_at: string;
  // Joined fields returned by some endpoints
  image?: Image;
  /** The environment's display name, joined in by the session listings. */
  image_name?: string | null;
  // Populated by the admin session listing so the console can name the owner.
  user_email?: string | null;
  user_full_name?: string | null;
}

// ---------------------------------------------------------
// Credit ledger
// ---------------------------------------------------------

export type LedgerReason = "grant" | "metering" | "refund" | "adjustment";

export interface LedgerEntry {
  id: string;
  user_id: string;
  delta: number;
  reason: LedgerReason;
  session_id: string | null;
  balance_after: number;
  created_at: string;
}

// ---------------------------------------------------------
// Usage summary
// ---------------------------------------------------------

export interface UsagePeriod {
  period: string; // e.g. "2024-07"
  gpu_minutes: number;
  cpu_minutes: number;
  credits_used: number;
}

// ---------------------------------------------------------
// Admin metrics
// ---------------------------------------------------------

// Mirrors AdminMetrics in backend/app/schemas.py. These names had drifted, so
// every tile in the console rendered "undefined".
export interface AdminMetrics {
  total_users: number;
  active_sessions: number;
  queued_sessions: number;
  gpus_free: number;
  gpus_leased: number;
  gpus_disabled: number;
  total_credits_granted: number;
  total_credits_used: number;
}

// ---------------------------------------------------------
// API response shapes
// ---------------------------------------------------------

export interface ApiError {
  detail: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

// Connect endpoint response
export interface ConnectResponse {
  url: string;
}
