"use client";

/**
 * Minimal typed API client for the AI Receptionist backend.
 * Auth token is kept in localStorage; requests go through the Next.js
 * rewrite proxy (/api → FastAPI), so no CORS setup is needed.
 */
const BASE = "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("air_token");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("air_token", token);
  else localStorage.removeItem("air_token");
}

export function getUser(): { id: string; email: string; full_name: string; role: string; tenant_id: string | null } | null {
  if (typeof window === "undefined") return null;
  const raw = localStorage.getItem("air_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

export function setUser(user: unknown) {
  if (typeof window === "undefined") return;
  if (user) localStorage.setItem("air_user", JSON.stringify(user));
  else localStorage.removeItem("air_user");
}

export async function api<T = unknown>(
  path: string,
  options: { method?: string; body?: unknown; formData?: FormData; auth?: boolean } = {}
): Promise<T> {
  const { method = "GET", body, formData, auth = true } = options;
  const headers: Record<string, string> = {};
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: formData ? formData : body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401 && auth && typeof window !== "undefined") {
    setToken(null);
    setUser(null);
    if (!window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError(401, "Session expirée");
  }

  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail =
      typeof data.detail === "string"
        ? data.detail
        : Array.isArray(data.detail)
        ? data.detail.map((d: { msg?: string }) => d.msg).join(", ")
        : `Erreur ${res.status}`;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

// ---- Shared types ---------------------------------------------------------- //
export interface TenantInfo {
  id: string;
  slug: string;
  name: string;
  sector: string;
  description: string;
  address: string;
  phone: string;
  email: string;
  website: string;
  timezone: string;
  languages: string[];
  currency: string;
  business_hours: Record<string, { open: string; close: string } | null>;
}

export interface ReceptionistInfo {
  name: string;
  avatar_url: string;
  voice: string;
  language: string;
  tone: string;
  style: string;
  conciseness: number;
  greeting: string;
  instructions: { do?: string[]; avoid?: string[]; ask?: string[]; transfer?: string[] };
  services: { name: string; duration_min: number; description: string; price: string }[];
  is_published: boolean;
  published_at: string | null;
  widget_url: string;
}

export interface ChatResponse {
  conversation_id: string;
  reply: string;
  intent: string;
  confidence: number;
  sources: { source_id: string | null; name: string; snippet: string }[];
  actions: { tool: string; status: string; result: Record<string, unknown>; message: string }[];
  handoff: boolean;
}

export interface Conversation {
  id: string;
  channel: string;
  status: string;
  intent: string;
  confidence: number;
  summary: string;
  resolution: string;
  created_at: string;
  updated_at: string;
  contact_name: string;
}

export interface Message {
  id: string;
  role: string;
  content: string;
  intent: string;
  confidence: number;
  sources: { source_id: string | null; name: string; snippet: string }[];
  meta: Record<string, unknown>;
  created_at: string;
}
