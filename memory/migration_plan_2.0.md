# Date Spark 2.0 — Reuse Map & Incremental Build Order
_2026‑06 · planning only, no code changed. Companion to assessment_2.0.md._

## A. Vision → existing capability mapping
| 2.0 capability | Exists today | Reuse | Gap |
|---|---|---|---|
| Who the experience is for | `relationship_type` (partner/date/friends/family/group/special) | ✅ keep as the Couple/Friends/Family entries | needs `experience_type` umbrella (couple, friends, family, celebration, travel, solo, surprise) + `party_size` |
| Location | GPS + city/ZIP → `location{label,lat,lng}`; Places text search w/ locationBias; Nominatim fallback | ✅ unchanged | travel mode: "I'm visiting X" = same geocode path |
| Date/time | `date_label/time_label/scheduled_at` (set after generation on share screen) | ✅ | move "when" + "available hours" into the input flow so the engine can use hours |
| Budget | 5 fixed bands | ✅ | add free‑form amount (e.g. $150) → `budget_amount` + `party_size` → per‑person math |
| Available time | — | — | `duration_hours` (2h / half day / evening / full day) |
| Interests | `user_preferences.favorite_vibes` | ✅ | add `interests[]` free tags (live music, hiking, board games…) |
| Atmosphere/vibe | 8 vibes, multi‑select | ✅ | unchanged |
| Transport/distance | 5/10/25/anywhere miles | ✅ | add `transport` (walk / transit / drive) → influences stop spacing + travel estimates |
| Occasion | `occasion` (Premium) | ✅ | becomes first‑class in Celebration profile |
| Coherent multi‑step plan | `recommend.py` already outputs ordered activities with times, costs, venue refs; NORMAL/OCCASION/SURPRISE modes | ✅ 80% there | add travel legs between stops (distance/minutes from venue lat/lng — haversine already in `places.py`), total cost roll‑up, hours‑aware timing |
| Surprise me | SURPRISE mode (mystery for the invitee) | ✅ | add **"Surprise me" input mode** = minimal inputs (budget, when, who) → engine picks vibes itself |
| Real‑world intelligence | Places hours/rating/price; `needs_verification` flag | ✅ | weather + events providers slot into `places.py` provider layer |
| Make it happen | calendar w/ alerts, Google Maps deep links, share invite, RSVP ("I'm in") | ✅ | reservations/tickets/payments later via partner links → Phase 6 |
| Marketplace | admin `featured_experiences` | seed | Phase 7 |

## B. Design principle for the migration
**Additive only.** Every new input is an optional field with a default equal to today's behaviour, so:
- existing sparks in Mongo stay valid (no backfill needed);
- the current 4‑step dating wizard keeps working verbatim (it becomes the "Couple" profile);
- `POST /sparks/generate` stays backward compatible — the new fields extend `GenerateIn`.

## C. Incremental build order (smallest first)

### Increment 1 — Engine foundation (data + API, no UI change)  ← START HERE
Backend only; ~150 lines; zero visible change.
1. `GenerateIn` gains optional: `experience_type`, `party_size`, `budget_amount`, `duration_hours`, `interests[]`, `transport`, `when{date_label,time_label,scheduled_at}`, `surprise_me`. Defaults reproduce current behaviour (`experience_type` derived from `relationship_type`).
2. `recommend.py`: pass the new context to the prompt; add **travel legs** (haversine between consecutive verified venues → `travel_minutes`, `travel_miles`, mode‑aware speed) and **cost roll‑up** (`total_estimated_cost`, `per_person`). Add `mode = SURPRISE_ME` (engine chooses vibes). Hours‑aware: pass the chosen day's opening hours line to the model and instruct it to respect them (already partly in prompt).
3. `sparks` documents store the new fields (`experience_type`, `party_size`, `travel_legs[]`, `total_estimated_cost`); `serialize_spark` unchanged otherwise.
4. Split `server.py` into `routers/auth.py`, `routers/sparks.py`, `routers/admin.py` (pure move, same routes) so later phases don't bloat one file.
5. Admin `ai_settings` gains per‑experience‑type guidance (`guidance_by_type`) — editable later.
**Test:** existing testing‑agent suite must pass unchanged; new curl with `experience_type:"solo", party_size:1, budget_amount:60, duration_hours:3`.

### Increment 2 — Experience Profiles (Phase 2)
UI: Welcome/Home + Create step 1 gain a profile selector row (Couple · Friends · Family · Celebration · Travel · Solo · Surprise me). Choosing **Couple** = today's flow exactly. Others pre‑fill `experience_type`, show/hide relevant inputs (e.g. Travel asks "where are you visiting", Solo skips "who"). `wizard.tsx` adds the new fields. `user_preferences` gets `default_experience_type`, `interests[]`. Analytics: `experience_type_selected`.

### Increment 3 — Experience Builder inputs (Phase 3)
Add **one** new optional step "When & how long" (date/time chips reused from share screen, duration chips, transport chips, party size stepper) and a free‑amount budget field on the budget step. Interests chips on the vibe step. Still ≤ 60‑second flow because all are optional with smart defaults; "Surprise me" collapses the wizard to budget + when.

### Increment 4 — Engine output upgrade (Phase 4)
Results card + detail timeline render travel legs ("🚶 8 min · 0.4 mi"), total/per‑person cost, time‑window fit, and an "Adjust" sheet (shorter / cheaper / closer / different vibe) that re‑prompts with constraints — generalising today's empty‑state fixes. Plan "coherence" badge when all stops verified + open at those hours.

### Increment 5 — Real‑world intelligence (Phase 5)
Provider layer in `places.py`: `weather.py` (Open‑Meteo, no key) → indoor/outdoor steering; `events.py` (Ticketmaster/Eventbrite — key from you) → event stops with real start times and ticket URLs. `needs_verification` already covers partial data.

### Increment 6 — Make it happen (Phase 6)
Reuse calendar + maps + RSVP; add "Reserve" buttons from Places `websiteUri`/reservation links, ticket deep links, confirmation checklist on the detail page, reminder alarms already exist. Payments only when partners exist (RevenueCat stays for subscription; Stripe for tickets/bookings later).

### Increment 7 — Marketplace (Phase 7)
`providers` + `experiences` collections, partner role on `users`, admin approval, sponsored slots replacing static `featured_experiences`.

## D. Risk controls
- Feature flags in `app_config` (`features.experience_profiles`, `features.builder_v2`) so each increment can be toggled from the admin screen without redeploying.
- Keep Premium gating semantics: occasion/surprise stay Premium; new profiles are free; advanced builder inputs (duration/transport/interests) → Premium "Advanced personalization" as already promised in the paywall copy.
- No destructive migrations: new fields only; indexes added, never dropped.
