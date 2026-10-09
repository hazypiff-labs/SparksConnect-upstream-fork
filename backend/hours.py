"""Venue opening-hours evaluation (Increment 5 · Phase 1 — Venue Reliability).

Pure functions over the Google Places (New) payload already fetched by `places.py`.
Never guesses: when data is missing, ambiguous or outside Google's current-hours window the
result says so explicitly.

Vocabulary
  status      open | closed | closed_permanently | closed_temporarily | unknown
  confidence  confirmed  — from `currentOpeningHours` (Google's next-7-days data incl. special days)
              regular    — from `regularOpeningHours` (typical week; holidays/special events NOT reflected)
              none       — nothing reliable to evaluate against
"""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

CURRENT_HOURS_WINDOW_DAYS = 7
DEFAULT_STOP_MINUTES = 60
DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]  # Google: 0 = Sunday

REGULAR_NOTE = "Regular hours — confirm closer to the date"
UNVERIFIED = "Hours not verified"


# ---------------------------------------------------------------- parsing helpers
def parse_clock(text: str | None) -> time | None:
    """'6:00 PM' / '6 pm' / '18:30' → time. None when unparseable."""
    if not text:
        return None
    m = re.match(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*$", str(text), re.I)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").lower().replace(".", "")
    if h > 23 or mi > 59:
        return None
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    return time(h, mi)


def fmt_clock(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p")


def to_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def venue_local(plan_start_utc: datetime, utc_offset_minutes: int | None) -> datetime | None:
    """Plan start expressed in the venue's own local time (naive). None when the offset is unknown."""
    if utc_offset_minutes is None:
        return None
    return (plan_start_utc.astimezone(timezone.utc) + timedelta(minutes=utc_offset_minutes)).replace(tzinfo=None)


def _point(p: dict | None, anchor_week_start: date | None) -> datetime | None:
    """Google `open`/`close` point → naive datetime. Dated points (currentOpeningHours) use their date;
    undated points (regularOpeningHours) are placed in the week starting Sunday `anchor_week_start`."""
    if not p:
        return None
    hour, minute = int(p.get("hour", 0)), int(p.get("minute", 0))
    d = p.get("date")
    if d:
        try:
            return datetime(int(d["year"]), int(d["month"]), int(d["day"]), hour, minute)
        except (KeyError, ValueError, TypeError):
            return None
    if anchor_week_start is None or "day" not in p:
        return None
    return datetime.combine(anchor_week_start + timedelta(days=int(p["day"])), time(hour, minute))


def _intervals(periods: list[dict], around: date) -> list[tuple[datetime, datetime]] | str:
    """Open intervals near `around`. Returns the string 'always' for 24-hour venues."""
    week_start = around - timedelta(days=(around.weekday() + 1) % 7)  # Sunday on/before `around`
    out: list[tuple[datetime, datetime]] = []
    for per in periods or []:
        o = per.get("open") or {}
        if "close" not in per or per.get("close") is None:
            # Google encodes "open 24 hours" as a single period with open day 0 00:00 and no close.
            if int(o.get("hour", 0)) == 0 and int(o.get("minute", 0)) == 0:
                return "always"
            continue
        if o.get("date"):
            a, b = _point(o, None), _point(per["close"], None)
            if a and b:
                out.append((a, b if b > a else b + timedelta(days=1)))
            continue
        for offset in (-7, 0, 7):  # previous / this / next week so overnight spill-over is covered
            ws = week_start + timedelta(days=offset)
            a, b = _point(o, ws), _point(per["close"], ws)
            if a and b:
                out.append((a, b if b > a else b + timedelta(days=7)))
    return out


def _covered_dates(current_periods: list[dict]) -> tuple[date, date] | None:
    ds: list[date] = []
    for per in current_periods or []:
        for k in ("open", "close"):
            d = (per.get(k) or {}).get("date")
            if d:
                try:
                    ds.append(date(int(d["year"]), int(d["month"]), int(d["day"])))
                except (KeyError, ValueError, TypeError):
                    pass
    return (min(ds), max(ds)) if ds else None


# ---------------------------------------------------------------- public API
def visit_window(local_plan_start: datetime, stop_start: str | None, stop_end: str | None) -> tuple[datetime, datetime]:
    """Stop start/end as venue-local datetimes. Clock strings are assumed to be on the plan date; a stop
    that reads earlier than the plan start by more than 6 h is treated as after midnight (next day)."""
    st = parse_clock(stop_start)
    start = datetime.combine(local_plan_start.date(), st) if st else local_plan_start
    if st and (local_plan_start - start) > timedelta(hours=6):
        start += timedelta(days=1)
    et = parse_clock(stop_end)
    end = datetime.combine(start.date(), et) if et else start + timedelta(minutes=DEFAULT_STOP_MINUTES)
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _pick_source(venue: dict, visit_date: date, now_utc: datetime | None) -> tuple[list[dict] | None, str]:
    """Which periods to trust for `visit_date`: current (confirmed) inside Google's window, else regular."""
    current = venue.get("current_periods") or []
    covered = _covered_dates(current)
    today = (now_utc or datetime.now(timezone.utc)).date()
    within_window = covered is not None and covered[0] <= visit_date <= covered[1] and visit_date <= today + timedelta(days=CURRENT_HOURS_WINDOW_DAYS)
    if within_window:
        return current, "confirmed"
    regular = venue.get("periods") or []
    if regular:
        return regular, "regular"
    return None, "none"


def _result(status: str, confidence: str, detail: str, **extra: Any) -> dict:
    return {"status": status, "confidence": confidence, "detail": detail, "source": "google_places", **extra}


def evaluate_hours(venue: dict | None, plan_start_utc: datetime | None, stop_start: str | None, stop_end: str | None, now_utc: datetime | None = None) -> dict:
    """Open/closed state of `venue` for the stop. Always returns a dict; never implies certainty it lacks."""
    if not venue:
        return _result("unknown", "none", UNVERIFIED)
    bs = venue.get("business_status")
    if bs == "CLOSED_PERMANENTLY":
        return _result("closed_permanently", "confirmed", "Permanently closed")
    if bs == "CLOSED_TEMPORARILY":
        return _result("closed_temporarily", "confirmed", "Temporarily closed")
    if plan_start_utc is None:
        return _result("unknown", "none", f"{UNVERIFIED} — no date chosen")
    local = venue_local(plan_start_utc, venue.get("utc_offset_minutes"))
    if local is None:
        return _result("unknown", "none", f"{UNVERIFIED} — venue time zone unavailable")
    start, end = visit_window(local, stop_start, stop_end)
    periods, confidence = _pick_source(venue, start.date(), now_utc)
    if periods is None:
        return _result("unknown", "none", UNVERIFIED, checked_for=start.isoformat())
    intervals = _intervals(periods, start.date())
    if intervals == "always":
        return _result("open", confidence, "Open 24 hours" if confidence == "confirmed" else f"Open 24 hours · {REGULAR_NOTE}", checked_for=start.isoformat())
    hit = next(((a, b) for a, b in intervals if a <= start < b), None)
    if hit is None:
        day = DAY_NAMES[(start.weekday() + 1) % 7]
        later_today = sorted(a for a, _ in intervals if a.date() == start.date() and a > start)
        detail = f"Closed at {fmt_clock(start)} {day}" + (f" · opens {fmt_clock(later_today[0])}" if later_today else " · closed at that time")
        if confidence == "regular":
            detail += f" · {REGULAR_NOTE}"
        return _result("closed", confidence, detail, checked_for=start.isoformat())
    closes = hit[1]
    closes_before_end = end > closes
    detail = f"Open at {fmt_clock(start)} · closes {fmt_clock(closes)}" + (" — before this stop ends" if closes_before_end else "")
    if confidence == "regular":
        detail += f" · {REGULAR_NOTE}"
    return _result("open", confidence, detail, checked_for=start.isoformat(), closes_before_end=closes_before_end)


def hours_on_day(venue: dict, plan_start_utc: datetime | None, now_utc: datetime | None = None) -> dict:
    """Compact per-venue hint for the planning prompt: {'text': 'Sat 5:00 PM–11:00 PM', 'confidence': ...}."""
    bs = venue.get("business_status")
    if bs in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
        return {"text": "Closed (" + bs.split("_")[1].lower() + ")", "confidence": "confirmed"}
    if plan_start_utc is None:
        return {"text": "Unknown — no plan date", "confidence": "none"}
    local = venue_local(plan_start_utc, venue.get("utc_offset_minutes"))
    if local is None:
        return {"text": "Unknown", "confidence": "none"}
    periods, confidence = _pick_source(venue, local.date(), now_utc)
    if periods is None:
        return {"text": "Unknown", "confidence": "none"}
    intervals = _intervals(periods, local.date())
    day = DAY_NAMES[(local.weekday() + 1) % 7]
    if intervals == "always":
        return {"text": f"{day} open 24 hours", "confidence": confidence}
    todays = sorted((a, b) for a, b in intervals if a.date() == local.date())
    if not todays:
        return {"text": f"{day} closed", "confidence": confidence}
    return {"text": f"{day} " + ", ".join(f"{fmt_clock(a)}–{fmt_clock(b)}" for a, b in todays), "confidence": confidence}


def summarize(activities: list[dict]) -> dict:
    """Spark-level roll-up of per-stop `hours_status`."""
    out = {"confirmed_open": 0, "regular_open": 0, "closed": 0, "unverified": 0}
    for a in activities:
        h = a.get("hours_status") or {}
        st, conf = h.get("status"), h.get("confidence")
        if st == "open" and conf == "confirmed":
            out["confirmed_open"] += 1
        elif st == "open":
            out["regular_open"] += 1
        elif st in ("closed", "closed_permanently", "closed_temporarily"):
            out["closed"] += 1
        else:
            out["unverified"] += 1
    return out
