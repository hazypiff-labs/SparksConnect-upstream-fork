import { storage } from "@/src/utils/storage";

const BASE = `${process.env.EXPO_PUBLIC_BACKEND_URL}/api`;
const TOKEN_KEY = "datespark_auth_token";
const GUEST_KEY = "datespark_guest_id";

let premiumFlag = false;
export function setPremiumFlag(v: boolean) {
  premiumFlag = v;
}

function randomId() {
  const chars = "abcdefghijklmnopqrstuvwxyz0123456789";
  let out = "g_";
  for (let i = 0; i < 24; i++) out += chars[Math.floor(Math.random() * chars.length)];
  return out;
}

export async function getGuestId(): Promise<string> {
  let id = await storage.getItem<string | null>(GUEST_KEY, null);
  if (!id) {
    id = randomId();
    await storage.setItem(GUEST_KEY, id);
  }
  return id;
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

export async function api<T = any>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const [token, guest] = await Promise.all([getToken(), getGuestId()]);
  const headers: Record<string, string> = { "Content-Type": "application/json", "X-Guest-ID": guest };
  if (token) headers.Authorization = `Bearer ${token}`;
  if (premiumFlag) headers["X-Premium"] = "1";
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers, ...(init.headers as Record<string, string>) },
    body: init.json !== undefined ? JSON.stringify(init.json) : init.body,
  });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const data = await res.json();
      detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {}
    throw new ApiError(res.status, detail);
  }
  return res.json();
}

export function track(event: string, props: Record<string, unknown> = {}) {
  api("/events", { method: "POST", json: { event, props } }).catch(() => {});
}

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
};

export type User = {
  id: string;
  name: string;
  email: string;
  role: string;
  location: { label: string; lat?: number; lng?: number } | null;
  subscription_status: string;
  created_at: string | null;
};
