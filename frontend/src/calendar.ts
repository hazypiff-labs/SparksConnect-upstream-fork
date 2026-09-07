import { Platform } from "react-native";
import * as Calendar from "expo-calendar";

export type CalendarResult = { status: "added" | "denied" | "blocked" | "unsupported" };

async function pickCalendarId(): Promise<string | null> {
  if (Platform.OS === "ios") {
    const def = await Calendar.getDefaultCalendarAsync();
    return def?.id ?? null;
  }
  const cals = await Calendar.getCalendarsAsync(Calendar.EntityTypes.EVENT);
  const writable = cals.filter((c) => c.allowsModifications);
  return (writable.find((c) => c.isPrimary) ?? writable[0])?.id ?? null;
}

/** Adds the Spark to the device calendar with alerts 1 day and 1 hour before. */
export async function addSparkToCalendar(opts: { title: string; notes: string; location?: string | null; startsAt: Date; durationMinutes?: number; isOccasion?: boolean }): Promise<CalendarResult> {
  if (Platform.OS === "web") return { status: "unsupported" };
  let perm = await Calendar.getCalendarPermissionsAsync();
  if (perm.status !== "granted") {
    if (!perm.canAskAgain) return { status: "blocked" };
    perm = await Calendar.requestCalendarPermissionsAsync();
    if (perm.status !== "granted") return { status: perm.canAskAgain ? "denied" : "blocked" };
  }
  const calendarId = await pickCalendarId();
  if (!calendarId) return { status: "unsupported" };
  const endDate = new Date(opts.startsAt.getTime() + (opts.durationMinutes ?? 150) * 60 * 1000);
  const alarms = [{ relativeOffset: -60 }];
  if (opts.isOccasion) alarms.push({ relativeOffset: -1440 });
  await Calendar.createEventAsync(calendarId, {
    title: opts.title,
    notes: opts.notes,
    location: opts.location ?? undefined,
    startDate: opts.startsAt,
    endDate,
    alarms,
  });
  return { status: "added" };
}
