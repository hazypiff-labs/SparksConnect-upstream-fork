# Date Spark 2.0 — Increment 5 Plan: Real-World Intelligence (PROPOSED — awaiting approval)

## A. Assessment of current code

| Area | What exists today | Gap |
|---|---|---|
| Venue data (`backend/places.py`) | Google Places API (New) `places:searchText`, 5 results × up to 6 vibe queries per generation, Nominatim geocode fallback. Field mask already requests `regularOpeningHours` (→ `hours` = weekday description strings), `rating`, `priceLevel`, `location`, `googleMapsUri`. Every failure degrades to `[]` (never breaks generation). | Hours are free-text strings only — not machine-checkable. No `businessStatus` (closed permanently/temporarily), no `currentOpeningHours` (next 7 days incl. holidays), no `utcOffsetMinutes` (needed to evaluate "open at 7 PM on the plan date"). |
| Engine (`backend/recommend.py`) | `_venue_brief()` passes `open_hours` text to Claude; prompt asks it to "plan stops so venues are open". Post-processing marks `verified` only = "venue_id matched a Google result". `compute_travel_legs()` = haversine × fixed mph (walk 3 / transit 10 / drive 22). | Model may still pick a closed venue; nothing verifies hours after generation. Legs are straight-line only, no `source` field. |
| Output (`server.py`, Increment 4 UI) | `travel_legs[]`, cost roll-up, `needs_verification`, redaction for locked surprise recipients, flags `experience_profiles/builder/output`. Timeline labels legs "Straight-line estimate". | No per-stop open/closed state; no routing provider abstraction. |
| Credentials | `GOOGLE_PLACES_API_KEY` in `backend/.env`. | Unknown whether that key/project has **Routes API** enabled (likely restricted to Places). |

Cost note: because the current field mask already includes `regularOpeningHours`, each text search is **already billed at Google's Enterprise SKU**. Adding the extra hours fields below does **not** change the SKU → Phase 1 is cost-neutral.

## B. Phased plan

### Phase 1 — Venue reliability (build first; no new credentials, no new cost)
1. Extend the Places field mask with `places.businessStatus`, `places.regularOpeningHours.periods`, `places.currentOpeningHours`, `places.utcOffsetMinutes` (same SKU tier as today).
2. New `backend/hours.py`: pure function `evaluate_hours(venue, plan_date_utc, stop_start, stop_end) → {status, detail, source, confidence}` where
   - `status ∈ open | closed | closed_permanently | closed_temporarily | unknown`
   - `confidence ∈ confirmed` (inside `currentOpeningHours` 7-day window) | `regular` (from `regularOpeningHours.periods`, > 7 days out — "regular hours, confirm closer to the date") | `none` (no hours data or no plan date).
   - Handles overnight periods, 24-hour venues, missing `periods`, venue timezone via `utcOffsetMinutes`, stop times after midnight.
3. Engine: (a) before prompting, `_venue_brief()` gains `likely_open_at_plan_time: true|false|unknown` and permanently/temporarily closed venues are dropped from the candidate list; (b) after generation each activity gains `hours_status` (from step 2) and spark-level `hours_summary` = `{confirmed_open, closed, unverified}` counts. `needs_verification` becomes true if any stop is `closed` or `unknown`.
4. UI (flag `venue_hours`, default ON): Timeline stop badge — "✓ Open at 7:00 PM (Google)", "⚠ Closed at this time", "Hours not verified"; CostSummary/At-a-glance row "2 of 3 stops confirmed open"; `SparkCard` line when any stop is closed. Locked recipients receive nothing new (activities are already stripped).

### Phase 2 — Real travel routing (build second; needs your approval — see G)
1. New `backend/routing.py` with a provider interface `route_leg(from, to, mode, departure) → {miles, minutes, source, polyline?}`. Provider: **Google Routes API `computeRoutes`** (Essentials SKU) — one call per spark using the stops as `intermediates`, returning all legs at once (DRIVE / WALK / TRANSIT with `departureTime` for transit).
2. Mongo `route_cache` collection (additive, TTL index 7 days) keyed by `(from_place_id, to_place_id, mode)` — repeat generations in the same city cost nothing.
3. `compute_travel_legs()` extended: try provider → on success legs carry `source: "google_routes"`, `estimate: false`, `label: "Walk · 12 min · 0.6 mi · via Google Routes"`; on any failure (API disabled, quota, `NOT_FOUND` for transit in a city without GTFS, timeout) fall back to today's haversine leg with `source: "straight_line"`, `estimate: true`. Spark gains `routing_source`. Existing stored sparks (no `source`) are treated as straight-line.
4. UI (flag `real_routing`, default **OFF** until the key is enabled): leg connector shows "via Google Routes" vs current "Straight-line estimate — not a road, walking or transit route"; At-a-glance travel row names the source; mixed sparks (some legs routed, some not) label per leg. Surprise owner/recipient rules unchanged (legs only between revealed stops; stripped for locked recipients).
5. Privacy: only venue-to-venue coordinates are sent to Google (already Google data); the user's own location is never sent to the routing provider.

### Phase 3 — Weather (later; only if small & safe after 1–2)
- Provider: **Open-Meteo** (`forecast` endpoint, 16-day horizon, hourly precipitation probability / temperature / weather code; no key for non-commercial). Only attached when `scheduled_at` is within 16 days **and** a stop is outdoor-typed (park, trail, viewpoint, market…). Beyond horizon or on error → field absent, UI shows nothing (never "sunny" by default). Flag `weather`, default OFF.
- Decision needed: Date Spark sells Premium → Open-Meteo's terms require a commercial plan (**$29/mo Standard, 1M calls**). Alternative: skip weather until later.

### Phase 4 — Local events (later; research only now, see E)

## C. Files / components expected to change

Backend
- `places.py` — field mask + `_normalize()` (new fields `business_status`, `periods`, `current_periods`, `utc_offset_minutes`).
- `hours.py` (new) — hours evaluation; `routing.py` (new) — Routes provider + cache + fallback.
- `recommend.py` — candidate filtering, `_venue_brief()` hint, per-activity `hours_status`, `compute_travel_legs()` provider hook (async).
- `server.py` — new flags in `DEFAULT_CONFIG.features` (`venue_hours`, `real_routing`, later `weather`), `OUTPUT_FIELDS` += `hours_summary`, `routing_source`; `route_cache` TTL index at startup; `.env` key `GOOGLE_ROUTES_API_KEY` (falls back to `GOOGLE_PLACES_API_KEY` if the same key is enabled).
- `tests/test_venue_hours.py`, `tests/test_routing.py` (new); existing suites unchanged.

Frontend
- `src/api.ts` (types), `src/features.ts` (`hours`, `routing` flags), `src/plan.ts` (hours/route label helpers).
- `src/components/Timeline.tsx` (stop hours badge, leg source label), `src/components/CostSummary.tsx` (open-stops row, travel source), `src/components/SparkCard.tsx` (closed-stop warning line).
- `app/spark/[id].tsx` (pass flags), `app/admin.tsx` (two new rows in `FLAGS`).
- No new screens, no wizard changes, no new request fields.

## D. Database / API changes (all additive)
- `sparks.activities[]` += `hours_status {status, detail, confidence, source, checked_for}`, `business_status`.
- `sparks` += `hours_summary {confirmed_open, closed, unverified}`, `routing_source`.
- `sparks.travel_legs[]` += `source`, `estimate`; existing legs without `source` → treated as straight-line.
- New collection `route_cache` (TTL 7 days). No field removals, no migrations, no request-schema changes. `/shared/{id}` exposes the new spark-level fields via `OUTPUT_FIELDS`; redaction already blanks them for locked recipients.

## E. Provider options

| Need | Option | Credentials | Cost / limits | Verdict |
|---|---|---|---|---|
| Venue hours | Google Places (New) — extra fields on the existing call | existing key | No incremental cost (already Enterprise SKU). Places Pro/Enterprise free tiers 5k / 1k calls per month, then pay-as-you-go. | **Recommend** |
| Routing | **Google Routes API `computeRoutes`** (Essentials) | enable Routes API on the existing Cloud project; key restriction update (or new key) | **10,000 free calls/month**, then $5 / 1,000 (10k–100k), $4 / 1,000 above. Supports DRIVE, WALK, TRANSIT (transit needs departure time; coverage depends on GTFS feeds). ~3 calls per generation (one per spark) → ~3,300 free generations/month before cache. | **Recommend** — approval required |
| Routing | OpenRouteService | free API key | ~2,000 req/day, rate-limited; **no transit**; terms discourage commercial use. | Backup only |
| Routing | OSRM public demo | none | Demo-only, no SLA, production use prohibited; no transit. Self-hosting = ops burden. | Not recommended |
| Weather | Open-Meteo | none (non-commercial) / `apikey` (commercial) | Free: 10k/day non-commercial. Commercial: $29/mo (1M calls). 16-day horizon. | Recommend for Phase 3, needs commercial decision |
| Events | Ticketmaster Discovery API | free API key (your account) | 5,000 calls/day, 5 req/s; strong US/CA/EU coverage; attribution + link-to-Ticketmaster required. | Best later option |
| Events | Eventbrite | — | Public event-search endpoint was removed (2020); only your own organisation's events are searchable. | Not viable for discovery |
| Events | PredictHQ / SeatGeek | enterprise contract / partner access | Custom pricing, no public list. | Not for now |

## F. Testing & rollback

Backend (pytest, mocked HTTP + live)
- Hours: fixtures for open / closed / overnight (e.g. 6 PM–2 AM) / 24h / no `periods` / `CLOSED_PERMANENTLY` / `CLOSED_TEMPORARILY` / plan > 7 days out (→ `regular` confidence) / no `scheduled_at` (→ `unknown`) / venue in a different timezone from the user.
- Routing: provider success (all three modes), 403 (API not enabled), 429 quota, timeout, transit `NOT_FOUND` → straight-line fallback with `estimate: true`; cache hit avoids a second call; legacy legs without `source`.
- Flags: `venue_hours`/`real_routing` OFF → prompt, legs and stored shape identical to Increment 4; flag independence with the three existing flags; legacy Couple payload unchanged; `/shared` + locked recipient redaction still blank legs/costs/hours summary.
- Live: one generation asserting every activity has `hours_status` and every leg has `source`.

Frontend (testing_agent)
- Stop badges (open / closed / unverified), leg source labels, flags OFF restores Increment 4 UI exactly, admin rows toggle via UI, surprise owner vs recipient, no red screens, no flash.

Rollback
- Each phase behind its own flag (admin switch, no redeploy). Turning a flag OFF restores previous behaviour instantly; the engine never fails on provider errors (fallbacks are the existing code paths). All fields additive, so rolling code back leaves stored sparks readable.

## G. Risks, uncertainties, decisions for approval

1. **Enable Google Routes API** on the existing Cloud project/key (or provide a new key with Routes enabled). Cost: $0 up to 10k calls/month, then $5/1k. `real_routing` ships OFF until you confirm. — *approve / defer*
2. **Hours confidence policy**: beyond Google's 7-day `currentOpeningHours` window we show "Regular hours — confirm closer to the date" rather than "Open". Agree?
3. **Candidate filtering**: drop venues Google marks closed (permanently/temporarily) before the model sees them — reduces choice slightly, removes a whole class of bad plans. Agree?
4. **Weather commercial terms**: Open-Meteo requires a $29/mo plan for a commercial app. Options: (a) defer weather, (b) approve the plan, (c) build it flag-OFF against the free endpoint for internal testing only.
5. **Events**: Ticketmaster is the only viable free provider; needs your API key and attribution. Research only this increment — confirm.
6. **Existing Places spend**: today's field mask is already Enterprise-tier (up to 6 text searches per generation). Not changed by this plan, but worth knowing; I can add a cheaper two-step (Pro search → Enterprise details only for chosen venues) in a later increment if volume grows.
7. Uncertainties: transit routing coverage varies by city (fallback handles it); LLM stop times are venue-local strings — we evaluate hours using the venue's own UTC offset, so travel-profile plans in another timezone remain correct; routing adds ~0.5–1.5 s to generation (cached thereafter).

Scope guard: no reservations, ticketing, payments, marketplace; engine extended not replaced; Couple/Surprise/Premium/profile/builder/output behaviour untouched.
