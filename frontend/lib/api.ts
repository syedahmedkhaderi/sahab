// ---------------------------------------------------------
// Typed fetch client for the Sahab control-plane API.
// Reads NEXT_PUBLIC_API_BASE (default "/api") as the base
// path. Cookies are sent automatically (credentials: "include").
// ---------------------------------------------------------

import type {
  User,
  UserRole,
  Session,
  Image,
  Rate,
  LedgerEntry,
  UsagePeriod,
  GpuInventory,
  AdminMetrics,
  ConnectResponse,
} from "./types";

const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE?.replace(/\/$/, "") ?? "/api";

// ---------------------------------------------------------
// Low-level fetch helper
// ---------------------------------------------------------

class ApiClientError extends Error {
  status: number;
  detail: string;

  constructor(status: number, detail: string) {
    super(detail);
    this.name = "ApiClientError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      detail = body?.detail ?? detail;
    } catch {
      // body is not JSON — keep default
    }
    throw new ApiClientError(res.status, detail);
  }

  // 204 No Content
  if (res.status === 204) return undefined as T;

  return res.json() as Promise<T>;
}

function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: "GET" });
}

function post<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function patch<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PATCH",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method: "PUT",
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
}

function del<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" });
}

export { ApiClientError };

// ---------------------------------------------------------
// Auth
// ---------------------------------------------------------

export interface SignupPayload {
  email: string;
  full_name: string;
  password: string;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface VerifyPayload {
  token: string;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export const auth = {
  signup: (payload: SignupPayload) =>
    post<{ message: string }>("/auth/signup", payload),

  verify: (payload: VerifyPayload) =>
    post<{ message: string }>("/auth/verify", payload),

  login: (payload: LoginPayload) =>
    post<AuthResponse>("/auth/login", payload),

  logout: () => post<{ message: string }>("/auth/logout"),
};

// ---------------------------------------------------------
// Current user
// ---------------------------------------------------------

export const me = {
  get: () => get<User>("/me"),
  updateProfile: (payload: { full_name?: string; password?: string }) =>
    patch<User>("/me", payload),
};

// ---------------------------------------------------------
// Sessions
// ---------------------------------------------------------

export interface CreateSessionPayload {
  resource_type: "l4_gpu" | "cpu";
  image_id: string;
  fallback_cpu?: boolean;
}

export const sessions = {
  list: () => get<Session[]>("/sessions"),
  get: (id: string) => get<Session>(`/sessions/${id}`),
  create: (payload: CreateSessionPayload) =>
    post<Session>("/sessions", payload),
  stop: (id: string) => post<Session>(`/sessions/${id}/stop`),
  connect: (id: string) => get<ConnectResponse>(`/sessions/${id}/connect`),
};

// ---------------------------------------------------------
// Catalog
// ---------------------------------------------------------

export const images = {
  list: () => get<Image[]>("/images"),
};

export const rates = {
  list: () => get<Rate[]>("/rates"),
};

// ---------------------------------------------------------
// Credits / ledger
// ---------------------------------------------------------

export const credits = {
  ledger: () => get<LedgerEntry[]>("/credits/ledger"),
  usage: () => get<UsagePeriod[]>("/usage"),
};

// ---------------------------------------------------------
// Admin
// ---------------------------------------------------------

export interface AdminUpdateUserPayload {
  full_name?: string;
  role?: UserRole;
  status?: "active" | "pending" | "disabled";
}

export interface AdminGrantCreditsPayload {
  amount: number;
  reason?: string;
}

export interface AdminCreateUserPayload {
  email: string;
  full_name: string;
  password: string;
  role?: UserRole;
}

export interface AdminUpdateRatePayload {
  resource_type: "l4_gpu" | "cpu";
  credits_per_minute: number;
}

export interface AdminImagePayload {
  name: string;
  docker_ref: string;
  kind: "gpu" | "cpu";
  is_default?: boolean;
  enabled?: boolean;
}

export const admin = {
  // Users
  listUsers: () => get<User[]>("/admin/users"),
  createUser: (payload: AdminCreateUserPayload) =>
    post<User>("/admin/users", payload),
  updateUser: (id: string, payload: AdminUpdateUserPayload) =>
    patch<User>(`/admin/users/${id}`, payload),
  grantCredits: (id: string, payload: AdminGrantCreditsPayload) =>
    post<LedgerEntry>(`/admin/users/${id}/credits`, payload),

  // Sessions
  listSessions: () => get<Session[]>("/admin/sessions"),
  stopSession: (id: string) => post<Session>(`/admin/sessions/${id}/stop`),

  // GPUs
  listGpus: () => get<GpuInventory[]>("/admin/gpus"),

  // Rates
  setRates: (payload: AdminUpdateRatePayload[]) =>
    put<Rate[]>("/admin/rates", payload),

  // Images
  createImage: (payload: AdminImagePayload) =>
    post<Image>("/admin/images", payload),
  updateImage: (id: string, payload: Partial<AdminImagePayload>) =>
    patch<Image>(`/admin/images/${id}`, payload),

  // Metrics
  metrics: () => get<AdminMetrics>("/admin/metrics"),
};
