import * as Crypto from "expo-crypto";

import { storage } from "@/src/utils/storage";

/** Validates the build-time backend URL (Expo inlines EXPO_PUBLIC_* when the bundle is built). */
export function backendConfigError(url: string | undefined): string | null {
  return url && /^https?:\/\/[^/\s]+/.test(url) ? null : "This build is missing EXPO_PUBLIC_BACKEND_URL.";
}

const BACKEND_URL = (process.env.EXPO_PUBLIC_BACKEND_URL ?? "").replace(/\/+$/, "");
/** Shown by the root layout when the build was made without a backend URL (instead of every call failing). */
export const configError = backendConfigError(BACKEND_URL);
const BASE = `${BACKEND_URL}/api`;
const TOKEN_KEY = "datespark_auth_token";
const GUEST_KEY = "datespark_guest_id";
const DEFAULT_TIMEOUT_MS = 20_000;

let premiumFlag = false;
export function setPremiumFlag(v: boolean) {
  premiumFlag = v;
}

/** The guest id is the only credential for guest data, so it comes from a CSPRNG (audit M5). */
function newGuestId() {
  return `g_${Crypto.randomUUID().replace(/-/g, "")}`;
}

export async function getGuestId(): Promise<string> {
  let id = await storage.getItem<string | null>(GUEST_KEY, null);
  if (!id) {
    id = newGuestId();
    await storage.setItem(GUEST_KEY, id);
  }
  return id;
}

/** New guest identity — called on logout so the next person on this device doesn't inherit (or gift) guest data. */
export async function rotateGuestId(): Promise<void> {
  await storage.setItem(GUEST_KEY, newGuestId());
}

export const getToken = () => storage.secureGet<string | null>(TOKEN_KEY, null);
export const setToken = (t: string | null) => (t ? storage.secureSet(TOKEN_KEY, t) : storage.secureRemove(TOKEN_KEY));

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

const SIGN_IN_PATHS = ["/auth/login", "/auth/signup", "/auth/apple", "/auth/google", "/auth/password/"];
let onUnauthorized: (() => void) | null = null;
/** The session registers a handler that signs the user out when the server rejects their token (audit H6). */
export function setUnauthorizedHandler(fn: (() => void) | null) {
  onUnauthorized = fn;
}

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown; timeoutMs?: number } = {}): Promise<T> {
  if (configError) throw new ApiError(0, configError);
  const [token, guest] = await Promise.all([getToken(), getGuestId()]);
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Guest-ID": guest };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (premiumFlag) headers["X-Premium"] = "1";
  const { json, timeoutMs, ...rest } = init;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs ?? DEFAULT_TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...rest,
      signal: controller.signal,
      headers: { ...headers, ...(rest.headers as Record<string, string>) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch (e) {
    const aborted = e instanceof Error && e.name === "AbortError";
    throw new ApiError(0, aborted ? "The request timed out. Check your connection and try again." : "Can't reach Date Spark right now. Check your connection.");
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    // A 401 from a sign-in attempt means "wrong credentials", not "your session died" — never sign out for those.
    if (res.status === 401 && token && !SIGN_IN_PATHS.some((p) => path.startsWith(p))) onUnauthorized?.();
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : "Please check your details and try again.";
    } catch {}
    throw new ApiError(res.status, detail);
  }
  const text = await res.text();
  return (text ? JSON.parse(text) : null) as T;
}

export function track(event: string, props: Record<string, unknown> = {}) {
  api("/events", { method: "POST", json: { event, props } }).catch(() => {});
}

export type HoursStatus = {
  status: "open" | "closed" | "closed_permanently" | "closed_temporarily" | "unknown";
  confidence: "confirmed" | "regular" | "none";
  detail: string;
  source: string;
  checked_for?: string;
  closes_before_end?: boolean;
};

export type Activity = {
  activity_name: string;
  venue: string | null;
  address: string | null;
  lat: number | null;
  lng: number | null;
  rating: number | null;
  hours: string[] | null;
  start_time: string | null;
  end_time: string | null;
  estimated_cost: string | null;
  external_url: string | null;
  note: string | null;
  verified: boolean;
  locked?: boolean;
  /** Venue reliability (Increment 5 · Phase 1). Absent on older sparks or when the flag was off. */
  hours_status?: HoursStatus | null;
};

export type HoursSummary = { confirmed_open: number; regular_open: number; closed: number; unverified: number };

export type TravelLeg = {
  from_index: number;
  to_index: number;
  miles: number;
  minutes: number;
  mode: string;
  label: string;
  /** Increment 5 · Phase 2 — "google_routes" | "straight_line". Missing on older sparks = straight-line. */
  source?: string;
  estimate?: boolean;
};

export type Spark = {
  id: string;
  title: string;
  emoji: string;
  tagline: string;
  description: string;
  primary_vibe: string;
  vibe_tags: string[];
  estimated_cost: string;
  estimated_duration: string;
  why: string;
  activities: Activity[];
  location_label: string;
  distance_miles: number | null;
  lat: number | null;
  lng: number | null;
  needs_verification: boolean;
  relationship_type: string;
  vibe: string[];
  budget: string;
  distance: string;
  date_label: string | null;
  time_label: string | null;
  scheduled_at: string | null;
  occasion: string | null;
  surprise: boolean;
  revealed_steps: number;
  dress_code: string | null;
  locked_for_recipient?: boolean;
  meet_time?: string | null;
  meet_place?: string | null;
  status: string;
  saved: boolean;
  is_owner?: boolean;
  created_at: string | null;
  completed_at: string | null;
  /** Experience Engine output (Increment 1 data, Increment 4 UI). All optional — older sparks lack them. */
  travel_legs?: TravelLeg[] | null;
  total_travel_minutes?: number | null;
  total_travel_miles?: number | null;
  total_estimated_cost?: number | null;
  per_person_cost?: number | null;
  priced_stops?: number | null;
  unpriced_stops?: number | null;
  experience_type?: string | null;
  party_size?: number | null;
  budget_amount?: number | null;
  duration_hours?: number | null;
  transport?: string | null;
  hours_summary?: HoursSummary | null;
  routing_source?: "google_routes" | "mixed" | "straight_line" | null;
};

export type User = {
  id: string;
  name: string;
  email: string;
  email_verified: boolean;
  role: string;
  location: { label: string; lat?: number; lng?: number } | null;
  subscription_status: string;
  created_at: string | null;
};
