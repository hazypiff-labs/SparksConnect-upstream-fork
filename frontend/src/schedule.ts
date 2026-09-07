/** Turn the friendly date/time chips into a concrete Date for calendars and surprise unlocks. */
export function computeScheduledAt(dateLabel: string | null, timeLabel: string | null, customDate = ""): Date | null {
  if (!dateLabel) return null;
  const base = new Date();
  base.setSeconds(0, 0);
  let day: Date | null = null;
  if (dateLabel === "Today") day = base;
  else if (dateLabel === "Tomorrow") {
    day = new Date(base);
    day.setDate(day.getDate() + 1);
  } else if (dateLabel === "This Weekend") {
    day = new Date(base);
    const dow = day.getDay(); // 0 Sun … 6 Sat
    const add = dow === 6 ? 0 : dow === 0 ? 0 : 6 - dow;
    day.setDate(day.getDate() + add);
  } else {
    const text = (customDate || dateLabel).trim();
    if (!text) return null;
    let parsed = new Date(text);
    if (isNaN(parsed.getTime())) parsed = new Date(`${text} ${base.getFullYear()}`);
    if (isNaN(parsed.getTime())) return null;
    if (parsed < base && !/\d{4}/.test(text)) parsed.setFullYear(parsed.getFullYear() + 1);
    day = parsed;
  }
  const { hours, minutes } = parseTime(timeLabel) ?? { hours: 19, minutes: 0 };
  const result = new Date(day);
  result.setHours(hours, minutes, 0, 0);
  return result;
}

export function parseTime(label: string | null): { hours: number; minutes: number } | null {
  if (!label) return null;
  const m = label.trim().match(/^(\d{1,2})(?::(\d{2}))?\s*(AM|PM)?$/i);
  if (!m) return null;
  let hours = parseInt(m[1], 10);
  const minutes = m[2] ? parseInt(m[2], 10) : 0;
  const ampm = m[3]?.toUpperCase();
  if (ampm === "PM" && hours < 12) hours += 12;
  if (ampm === "AM" && hours === 12) hours = 0;
  return { hours, minutes };
}

export function formatScheduled(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  if (isNaN(d.getTime())) return null;
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
