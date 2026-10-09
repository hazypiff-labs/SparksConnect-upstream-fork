import type { HoursStatus, Spark, TravelLeg } from "@/src/api";
import { DURATIONS, TRANSPORTS } from "@/src/constants";

export type HoursTone = "good" | "warn" | "neutral";

/** User-facing badge for a stop's verified hours. Never implies certainty the data lacks. */
export function hoursBadge(h: HoursStatus | null | undefined): { text: string; tone: HoursTone; hint?: string } | null {
  if (!h) return null;
  switch (h.status) {
    case "closed_permanently":
      return { text: "Permanently closed", tone: "warn" };
    case "closed_temporarily":
      return { text: "Temporarily closed", tone: "warn" };
    case "closed":
      return { text: h.confidence === "confirmed" ? "Closed at this time" : "Usually closed at this time", tone: "warn", hint: h.detail };
    case "open":
      if (h.confidence === "confirmed") return { text: h.closes_before_end ? "Open · closes before this stop ends" : "Open at this time", tone: h.closes_before_end ? "warn" : "good", hint: h.detail };
      return { text: "Regular hours — confirm closer to the date", tone: "neutral", hint: h.detail };
    default:
      return { text: "Hours not verified", tone: "neutral" };
  }
}

/** "6:00 PM" → minutes since midnight, or null when unparseable. */
export function parseClock(text: string | null | undefined): number | null {
  if (!text) return null;
  const m = /^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*$/i.exec(text);
  if (!m) return null;
  let h = parseInt(m[1], 10);
  const min = m[2] ? parseInt(m[2], 10) : 0;
  const ap = m[3]?.toLowerCase().replace(/\./g, "");
  if (h > 23 || min > 59) return null;
  if (ap === "pm" && h < 12) h += 12;
  if (ap === "am" && h === 12) h = 0;
  return h * 60 + min;
}

/** Minutes a stop lasts, from its start/end clock times. Null when either is missing or the span is implausible. */
export function stopDurationMinutes(start: string | null | undefined, end: string | null | undefined): number | null {
  const a = parseClock(start);
  const b = parseClock(end);
  if (a == null || b == null) return null;
  let d = b - a;
  if (d < 0) d += 24 * 60; // crosses midnight
  return d > 0 && d <= 12 * 60 ? d : null;
}

export function formatMinutes(total: number): string {
  const m = Math.round(total);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rest = m % 60;
  return rest ? `${h} h ${rest} min` : `${h} h`;
}

export function formatMoney(n: number): string {
  return Number.isInteger(n) ? `$${n}` : `$${n.toFixed(2)}`;
}

export function formatMiles(miles: number): string {
  return miles < 0.1 ? "<0.1 mi" : `${Math.round(miles * 10) / 10} mi`;
}

export function transportEmoji(mode: string | null | undefined): string {
  return TRANSPORTS.find((t) => t.key === mode)?.emoji ?? "🚗";
}

export function transportLabel(mode: string | null | undefined): string {
  return TRANSPORTS.find((t) => t.key === mode)?.label ?? "Drive";
}

export function durationLabel(hours: number | null | undefined): string | null {
  if (hours == null) return null;
  return DURATIONS.find((d) => d.key === hours)?.label ?? `${hours} h`;
}

/** Legs whose both endpoints are within the first `visibleStops` stops (surprise owners only see revealed legs). */
export function visibleLegs(legs: TravelLeg[] | null | undefined, visibleStops: number): TravelLeg[] {
  return (legs ?? []).filter((l) => l.to_index < visibleStops);
}

/**
 * Cost figures we are allowed to show. Totals only exist when at least one stop carries a price;
 * per-person only when the party size is known. Unpriced stops are always surfaced, never guessed.
 */
export function costSummary(sp: Pick<Spark, "total_estimated_cost" | "per_person_cost" | "priced_stops" | "unpriced_stops" | "party_size">) {
  const priced = sp.priced_stops ?? 0;
  const unpriced = sp.unpriced_stops ?? 0;
  const total = sp.total_estimated_cost ?? null;
  if (total == null || priced === 0) return null;
  return {
    total,
    perPerson: sp.per_person_cost ?? null,
    partySize: sp.party_size ?? null,
    priced,
    unpriced,
    stops: priced + unpriced,
    complete: unpriced === 0,
  };
}

/** One compact line for result cards: "3 stops · ~25 min travel · $84 total ($21/person)". Null when nothing useful is known. */
export function glanceLine(sp: Spark): string | null {
  const parts: string[] = [];
  const stops = sp.activities?.length ?? 0;
  if (stops) parts.push(`${stops} ${stops === 1 ? "stop" : "stops"}`);
  if (sp.total_travel_minutes != null && (sp.travel_legs?.length ?? 0) > 0) parts.push(`~${formatMinutes(sp.total_travel_minutes)} travel`);
  const cost = costSummary(sp);
  if (cost) parts.push(`${formatMoney(cost.total)}${cost.complete ? "" : "+"} total${cost.perPerson != null ? ` (${formatMoney(cost.perPerson)}/person)` : ""}`);
  return parts.length > 1 ? parts.join(" · ") : null;
}
