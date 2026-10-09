"""AI recommendation engine: PERSON + PREFERENCES + LOCATION + CONTEXT = PERSONALIZED EXPERIENCE."""
import asyncio
import json
import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from emergentintegrations.llm.chat import LlmChat, UserMessage

from hours import evaluate_hours, hours_on_day, summarize as summarize_hours, to_utc
from places import haversine_miles, search_venues

logger = logging.getLogger("recommend")

# Approximate door-to-door speeds (mph) used for travel-leg estimates between verified venues.
TRANSPORT_SPEED_MPH = {"walk": 3.0, "transit": 10.0, "drive": 22.0}
TRANSPORT_LABEL = {"walk": "Walk", "transit": "Transit", "drive": "Drive"}

EXPERIENCE_TYPE_TEXT = {
    "couple": "a couple (date / relationship experience)",
    "friends": "a group of friends (shared outing)",
    "family": "a family (inclusive, all ages welcome)",
    "celebration": "a celebration (birthday, anniversary or special occasion)",
    "travel": "a traveler exploring a new place (local gems, easy logistics)",
    "solo": "one person treating themselves (solo-friendly, comfortable alone)",
    "surprise_me": "someone who wants to be surprised",
}

# Vibe → venue search queries (real-world data pulled from the place provider)
VIBE_QUERIES: dict[str, list[str]] = {
    "romantic": ["romantic restaurant", "scenic viewpoint or park", "dessert cafe"],
    "fun": ["arcade or bowling", "mini golf", "comedy club"],
    "adventurous": ["hiking trail", "kayak or bike rental", "climbing gym"],
    "relaxing": ["cozy coffee shop", "botanical garden or park", "tea house"],
    "foodie": ["highly rated restaurant", "food market or food hall", "bakery"],
    "creative": ["pottery or art class", "art gallery", "craft workshop"],
    "entertainment": ["live music venue", "movie theater", "escape room"],
    "different": ["unusual attraction", "night market or night event", "observatory or planetarium"],
}

BUDGET_TEXT = {
    "free": "FREE (no spending at all)",
    "under25": "$25 or less total",
    "25-50": "$25–$50 total",
    "50-100": "$50–$100 total",
    "100plus": "$100+ (premium is fine)",
}

RELATIONSHIP_TEXT = {
    "partner": "their long-term partner",
    "date": "a date (new or early connection)",
    "friends": "close friends",
    "family": "family (multi-generational, keep it inclusive)",
    "group": "a group of people",
    "special": "someone special to them",
    "solo": "themselves — a solo outing (comfortable and rewarding to do alone)",
}

SYSTEM_PROMPT = """You are Date Spark's experience designer. Your mission: help people create moments that bring them closer together in the real world.

Principles you always follow:
1. Favor real-world interaction, conversation, shared activities and memorable moments.
2. Build multi-stop combinations (e.g. Coffee → Scenic walk → Dessert) rather than a single venue.
3. Respect the stated budget and travel distance strictly.
4. Vary the three ideas: different energy levels, different formats. Never repeat titles the user already saw.
5. Use ONLY venues from the provided VENUES list when referencing a specific place; reference them by their exact venue_id. Never invent business names, addresses, prices, hours or availability.
6. If no listed venue fits a stop, set venue_id to null and describe the activity generically (e.g. "a scenic walk nearby") and set needs_verification true.
7. Keep language warm, modern and playful. Never sound like a dating app.

Return ONLY valid JSON (no markdown) with this exact shape:
{"sparks":[{
  "title": "THE COZY CONNECTION",
  "emoji": "❤️",
  "tagline": "Coffee → Scenic Walk → Dessert",
  "description": "2-3 sentence description",
  "primary_vibe": "Romantic",
  "vibe_tags": ["Romantic","Relaxed"],
  "estimated_cost": "$35–$50",
  "estimated_duration": "2.5 hours",
  "why": "1-2 sentences on why this fits this person + preferences",
  "dress_code": "only when SURPRISE mode: short dress-code hint, otherwise null",
  "activities": [
    {"name":"Coffee","venue_id":"<id or null>","start_time":"6:00 PM","end_time":"7:00 PM","estimated_cost":"$12","note":"short tip"}
  ]
}]}
Produce exactly 3 sparks. Normal mode: 2-4 activities each. OCCASION mode: 3-5 activities with occasion-specific touches (a toast, a keepsake, a photo moment, a meaningful closing stop). SURPRISE mode: the first activity is the meeting point (clear time + place); the description must be a teaser that does not spoil later stops; include a dress_code. SURPRISE_ME mode: the person gave only budget/time/company and wants you to choose the vibe — pick a bold, well-matched theme per spark and vary the three strongly. Activities always in chronological order.
When EXPERIENCE DETAILS are provided: respect party_size (group-friendly venues, costs are totals for the whole party), fit the whole plan inside duration_hours, keep the total within budget_amount when given, weave in the listed interests, and space stops for the transport mode (walking plans stay within ~1 mile between stops)."""

# Appended to the system prompt only when the `venue_hours` flag is on (keeps the legacy prompt byte-identical when off).
HOURS_RULE = "\nWhen venues carry hours_on_plan_day: never schedule a stop at a venue outside those hours or on a day it lists as closed; prefer venues whose hours are known; if you must use a venue whose hours are Unknown, set needs_verification true for that stop."


def apply_hours(activities: list[dict], venue_map: dict[str, dict], scheduled_at: str | None) -> dict:
    """Stamp each activity with `hours_status` and return the spark-level roll-up. Unmatched venues → unknown."""
    plan_start = to_utc(scheduled_at)
    for a in activities:
        a["hours_status"] = evaluate_hours(venue_map.get(a.get("venue_id") or ""), plan_start, a.get("start_time"), a.get("end_time"))
    return summarize_hours(activities)


def drop_closed_venues(venues: list[dict]) -> list[dict]:
    """Exclude venues Google explicitly marks closed. Never empties the list: if everything is flagged, keep the originals."""
    kept = [v for v in venues if v.get("business_status") not in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY")]
    return kept or venues


def parse_cost(text: str | None) -> float | None:
    """Best-effort USD parse of model/venue cost strings like "$35", "$25–$50" (midpoint), "Free". None if unknown."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    if "free" in t or t in ("$0", "0"):
        return 0.0
    nums = [float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t)]
    if not nums:
        return None
    if len(nums) >= 2:
        return round((nums[0] + nums[1]) / 2, 2)
    return nums[0]


def compute_travel_legs(activities: list[dict], transport: str | None) -> list[dict]:
    """Travel between consecutive stops that both have verified coordinates. Legs without coordinates are omitted."""
    speed = TRANSPORT_SPEED_MPH.get((transport or "drive").lower(), TRANSPORT_SPEED_MPH["drive"])
    mode = (transport or "drive").lower() if (transport or "drive").lower() in TRANSPORT_SPEED_MPH else "drive"
    legs: list[dict] = []
    for i in range(len(activities) - 1):
        a, b = activities[i], activities[i + 1]
        if None in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
            continue
        miles = round(haversine_miles(a["lat"], a["lng"], b["lat"], b["lng"]), 2)
        minutes = max(1, int(round(miles / speed * 60))) if miles > 0 else 0
        legs.append({"from_index": i, "to_index": i + 1, "miles": miles, "minutes": minutes, "mode": mode, "label": f"{TRANSPORT_LABEL[mode]} · {minutes} min · {miles} mi"})
    return legs


def cost_rollup(activities: list[dict], party_size: int | None) -> dict:
    """Sum known per-activity costs. Never invents a number: unknown stops are counted and flagged."""
    known: list[float] = []
    unknown = 0
    for a in activities:
        v = parse_cost(a.get("estimated_cost"))
        if v is None:
            unknown += 1
        else:
            known.append(v)
    total = round(sum(known), 2) if known else None
    per_person = round(total / party_size, 2) if total is not None and party_size and party_size > 0 else None
    return {"total_estimated_cost": total, "per_person_cost": per_person, "priced_stops": len(known), "unpriced_stops": unknown, "complete": unknown == 0 and bool(known)}


def when_text(scheduled_at: str | None, date_label: str | None, time_label: str | None, utc_offset_minutes: int | None = None) -> str:
    """Human-readable 'when' for the prompt. A concrete scheduled_at wins so the model can respect opening hours.
    Rendered in the venue area's local time when the offset is known (from Places) — otherwise a 7 PM Saturday
    plan in Austin would read as 'Sunday 12:00 AM'. Without venues there are no hours to respect, so UTC is kept."""
    if scheduled_at:
        try:
            dt = datetime.fromisoformat(str(scheduled_at).replace("Z", "+00:00"))
            if utc_offset_minutes is not None:
                dt = dt.astimezone(timezone.utc) + timedelta(minutes=utc_offset_minutes)
            return dt.strftime("%A %B %-d, %-I:%M %p") + (" local time" if utc_offset_minutes is not None else "") + " (plan stops so venues are open at these times)"
        except ValueError:
            pass
    return " ".join(x for x in [date_label, time_label] if x) or "not chosen yet"


def resolve_mode(surprise: bool, occasion: str | None, surprise_me: bool) -> str:
    """Existing SURPRISE and OCCASION modes take precedence; SURPRISE_ME is purely additive."""
    if surprise:
        return "SURPRISE"
    if occasion:
        return "OCCASION"
    if surprise_me:
        return "SURPRISE_ME"
    return "NORMAL"


def _slug_query_list(vibes: list[str]) -> list[str]:
    queries: list[str] = []
    for v in vibes or ["relaxing"]:
        queries.extend(VIBE_QUERIES.get(v, [])[:2])
    # Always include a conversational anchor
    queries.append("cozy coffee shop")
    seen, out = set(), []
    for q in queries:
        if q not in seen:
            seen.add(q)
            out.append(q)
    return out[:6]


async def gather_venues(lat: float, lng: float, radius_miles: float, vibes: list[str]) -> list[dict]:
    radius_m = min(radius_miles * 1609.34, 50000)
    results = await asyncio.gather(*[search_venues(q, lat, lng, radius_m, 5) for q in _slug_query_list(vibes)])
    venues: dict[str, dict] = {}
    for batch in results:
        for v in batch:
            if not v.get("id"):
                continue
            if v.get("distance_miles") is not None and radius_miles < 500 and v["distance_miles"] > radius_miles * 1.3:
                continue
            venues[v["id"]] = v
    return list(venues.values())[:24]


def _venue_brief(v: dict, plan_start: datetime | None = None, with_hours: bool = False) -> dict:
    brief = {
        "venue_id": v["id"],
        "name": v["name"],
        "address": v["address"],
        "rating": v.get("rating"),
        "price_level": v.get("price_level"),
        "distance_miles": v.get("distance_miles"),
        "open_hours": (v.get("hours") or [])[:7],
        "types": v.get("types"),
    }
    if with_hours:
        hint = hours_on_day(v, plan_start)
        brief["hours_on_plan_day"] = hint["text"] + ("" if hint["confidence"] == "confirmed" else f" ({hint['confidence']} hours)" if hint["confidence"] == "regular" else "")
    return brief


def _extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


async def generate_sparks(
    *,
    relationship_type: str,
    vibes: list[str],
    budget: str,
    distance: str,
    location: dict[str, Any],
    exclude_titles: list[str],
    history: dict[str, Any],
    date_label: str | None,
    time_label: str | None,
    ai_settings: dict[str, Any],
    occasion: str | None = None,
    surprise: bool = False,
    experience: dict[str, Any] | None = None,
    venue_hours: bool = False,
) -> list[dict]:
    experience = experience or {}
    surprise_me = bool(experience.get("surprise_me"))
    radius_miles = {"5": 5, "10": 10, "25": 25, "anywhere": 60}.get(str(distance), 10)
    lat, lng = location.get("lat"), location.get("lng")
    venues: list[dict] = []
    # SURPRISE_ME with no vibes: cast a wide net so the model can pick the theme.
    venue_vibes = vibes or (list(VIBE_QUERIES.keys()) if surprise_me else [])
    if lat is not None and lng is not None:
        venues = await gather_venues(lat, lng, radius_miles, venue_vibes)
    # Venue reliability: never offer venues Google marks closed (safe — keeps the list if all are flagged).
    if venue_hours:
        venues = drop_closed_venues(venues)
    venue_map = {v["id"]: v for v in venues}
    plan_start = to_utc(experience.get("scheduled_at"))
    # Local UTC offset of the venue area (from Places) so the plan time is described in local time, not UTC.
    area_offset = next((v["utc_offset_minutes"] for v in venues if v.get("utc_offset_minutes") is not None), None)

    context = {
        "spending_time_with": RELATIONSHIP_TEXT.get(relationship_type, relationship_type),
        "desired_vibes": vibes if vibes else "you choose (SURPRISE_ME)",
        "budget": BUDGET_TEXT.get(budget, budget),
        "max_travel_miles": radius_miles,
        "location_label": location.get("label") or "their area",
        "when": when_text(experience.get("scheduled_at"), date_label, time_label, area_offset),
        "user_favorite_vibes": history.get("favorite_vibes", []),
        "recently_saved_titles": history.get("saved_titles", [])[:5],
        "avoid_titles": exclude_titles[:12],
        "avoid_experience_types": history.get("recent_types", [])[:6],
        "admin_guidance": ai_settings.get("guidance", ""),
        "venues_available": bool(venues),
        "occasion": occasion or None,
        "mode": resolve_mode(surprise, occasion, surprise_me),
    }
    if experience:
        details = {k: v for k, v in experience.items() if k != "surprise_me"}
        if "experience_type" in details:
            details["experience_type"] = EXPERIENCE_TYPE_TEXT.get(details["experience_type"], details["experience_type"])
        if details:
            context["experience_details"] = details
    prompt = (
        "CONTEXT:\n" + json.dumps(context, ensure_ascii=False)
        + "\n\nVENUES (real data, reference by venue_id only):\n"
        + json.dumps([_venue_brief(v, plan_start, venue_hours) for v in venues], ensure_ascii=False)
        + ("\n\nNo venue data is available; design activity-based plans with venue_id null and needs_verification true." if not venues else "")
        + "\n\nDesign 3 Sparks now."
    )

    chat = LlmChat(
        api_key=os.environ["EMERGENT_LLM_KEY"],
        session_id=f"spark-{uuid.uuid4()}",
        system_message=SYSTEM_PROMPT + (HOURS_RULE if venue_hours else ""),
    ).with_model("anthropic", ai_settings.get("model", "claude-sonnet-4-6"))
    raw = await chat.send_message(UserMessage(text=prompt))
    data = _extract_json(raw if isinstance(raw, str) else str(raw))
    sparks: list[dict] = []
    for s in (data.get("sparks") or [])[:3]:
        activities = []
        needs_verification = False
        first_venue = None
        for a in s.get("activities") or []:
            v = venue_map.get(a.get("venue_id")) if a.get("venue_id") else None
            if v is None:
                needs_verification = True
            elif first_venue is None:
                first_venue = v
            activities.append(
                {
                    "activity_name": a.get("name") or "Activity",
                    "venue": v["name"] if v else None,
                    "venue_id": v["id"] if v else None,
                    "address": v["address"] if v else None,
                    "lat": v.get("lat") if v else None,
                    "lng": v.get("lng") if v else None,
                    "rating": v.get("rating") if v else None,
                    "hours": v.get("hours") if v else None,
                    "start_time": a.get("start_time"),
                    "end_time": a.get("end_time"),
                    "estimated_cost": a.get("estimated_cost"),
                    "external_url": v.get("maps_url") if v else None,
                    "note": a.get("note"),
                    "verified": v is not None,
                }
            )
        distance_miles = first_venue.get("distance_miles") if first_venue else None
        travel_legs = compute_travel_legs(activities, experience.get("transport"))
        costs = cost_rollup(activities, experience.get("party_size"))
        hours_summary = apply_hours(activities, venue_map, experience.get("scheduled_at")) if venue_hours else None
        sparks.append(
            {
                "title": s.get("title") or "A Spark",
                "emoji": s.get("emoji") or "✨",
                "tagline": s.get("tagline") or "",
                "description": s.get("description") or "",
                "primary_vibe": s.get("primary_vibe") or (vibes[0].title() if vibes else "Connection"),
                "vibe_tags": s.get("vibe_tags") or [],
                "estimated_cost": s.get("estimated_cost") or BUDGET_TEXT.get(budget, budget),
                "estimated_duration": s.get("estimated_duration") or "2 hours",
                "why": s.get("why") or "",
                "dress_code": (s.get("dress_code") or None) if surprise else None,
                "activities": activities,
                "location_label": first_venue["address"] if first_venue else (location.get("label") or "Your area"),
                "distance_miles": distance_miles,
                "lat": first_venue.get("lat") if first_venue else lat,
                "lng": first_venue.get("lng") if first_venue else lng,
                "needs_verification": needs_verification,
                # Experience Engine foundation (additive)
                "travel_legs": travel_legs,
                "total_travel_minutes": sum(l["minutes"] for l in travel_legs) if travel_legs else None,
                "total_travel_miles": round(sum(l["miles"] for l in travel_legs), 2) if travel_legs else None,
                **costs,
                # Venue reliability (Increment 5 · Phase 1) — only present when the flag is on
                **({"hours_summary": hours_summary} if venue_hours else {}),
            }
        )
    return sparks
