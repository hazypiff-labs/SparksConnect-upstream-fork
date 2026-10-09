# Date Spark ✨ — PRD & Build Log

## Original problem statement
Build "Date Spark", a connection-and-experience planning mobile app (NOT a dating app). Flow: Welcome → Who are you with → Vibe(s) → Budget → Distance/location → 3 AI-generated "Sparks" → Spark detail (map, itinerary) → "Spark It" shareable invitation. Includes My Sparks (Saved/Created/Completed), guest-first accounts, Premium ($24.99/mo, configurable free limit), admin dashboard, analytics events, real venue data (never fabricated), warm/modern/playful design with ✨ identity.

## User choices
- AI: Claude Sonnet 4.6 via Emergent Universal Key
- Venue data: Google Places API (New) — key provided; **Places API (New) must be enabled in the user's Google Cloud project** (currently 403 SERVICE_DISABLED → app falls back to AI-only plans flagged "needs verification")
- Auth: guest-first (X-Guest-ID) + email/password JWT; guest data migrates on signup
- Premium: Emergent-managed RevenueCat, $24.99/mo, **2-week free trial for everyone** (Test Store in preview)
- Admin dashboard inside the app (admin role)

## Architecture
- `backend/server.py` FastAPI + Motor/MongoDB: config, auth, sparks CRUD, share/complete, analytics events, admin stats/config
- `backend/recommend.py` recommendation engine (venue gathering + Claude JSON plan; multi-stop itineraries; excludes seen titles; uses saved/pref history)
- `backend/places.py` provider layer (Google Places text search, Nominatim geocode fallback)
- Frontend Expo Router: `app/index.tsx` welcome, `(tabs)` Home/My Sparks/Create/Profile (NativeTabs on iOS 26+), `create/*` wizard, `spark/[id]`, `share/[id]`, `auth`, `premium`, `admin`
- `src/session.tsx` (auth + RevenueCat identity binding + subscription mirror), `src/revenuecat.tsx`, `src/wizard.tsx`, `src/api.ts`
- Collections: users, user_preferences, sparks (activities embedded), saved_sparks, subscriptions, analytics_events, app_config

## Implemented (2026-06)
- Full 60-second flow end-to-end; 3 Spark cards; detail w/ itinerary timeline + map (native) / placeholder (web); Spark It with date/time + native share + copy
- Save / Created / Completed sections; guest → account migration; soft-delete account
- Free monthly limit (admin-configurable), 402 → paywall; X-Premium bypass for entitled users
- Premium paywall with RevenueCat package, restore, confirm sheet; trial days from config
- Admin dashboard: users, active, generated/saved/shared/completed, premium, MRR, conversion, generate→share rate, popular relationships/vibes/locations/experiences; config for free limit, price (display), trial days, promo message, AI guidance, featured experiences
- Analytics events: app_opened, signup_started/completed, spark_started, relationship/vibe/budget/location_selected, sparks_generated, spark_viewed/saved/shared/completed, premium_viewed, subscription_started
- Empty/error state with Expand / Lower budget / Increase distance / Different vibe
- Iteration 2 (2026-06): Google login (Emergent-managed, `POST /api/auth/session` → own JWT, web redirect + mobile openAuthSessionAsync), invitation links (share_url via Linking.createURL; recipient view with invite banner, "I'm in" save + sign-up prompt), occasion planning (Premium; occasion chips on Who step; richer 3–5 stop plans; scheduled_at computed from date/time chips; add to device calendar with 1h/1d alerts via expo-calendar), Surprise Spark (Premium; owner reveals stops one by one via `PUT /sparks/{id}/reveal`; recipient sees only meet time/place + dress code until scheduled_at passes). Tested iteration 2: backend 8/8, frontend flows pass.
- Google sign-in surfaced on Welcome screen too (welcome-google-button) — 2026-06.
- Sign in with Apple (2026-06): native Apple button on iOS (`expo-apple-authentication`), backend `POST /api/auth/apple` verifies identity token against Apple JWKS (aud = bundle id + host.exp.Exponent), users keyed by `apple_sub`, links existing email accounts, guest Sparks migrate. Requires iOS device / build to exercise the button.
- Tested: backend 14/14, frontend flows pass (iteration 1)

## Backlog
- P0: User enables Places API (New) so venues/addresses/hours are real
- P1: Google/Apple sign-in; deep-link handling for datespark://spark/{id} recipient view; Completed flow prompt after date passes
- P1: Premium features: surprise Spark mode, special-occasion planning, advanced budget/distance controls
- P2: subscription_cancelled event via RevenueCat webhook; dark theme values; experience imagery per vibe

## Android package renamed (2026-06)
- app.json android.package = com.date_spark.myapp (was com.emergent.vibefinder.rvztki). iOS bundleIdentifier unchanged. RevenueCat Play app re-synced.

## Phase A — Subscription security & cost protection (2026‑06) ✅ (audit B‑1/B‑2/B‑3)
- `backend/limits.py`: atomic Mongo limiter reserved before Claude/Places. Layers: per‑IP hourly/daily (20/80), new‑guest‑ids per IP per day (20), identity: free monthly (`free_spark_limit`, 402) or bounded premium ceilings when `X-Premium` is *claimed* (15/day, 60/month, 429). Fail‑closed. Receipts released on engine failure (identity units only). Admin‑tunable `app_config.limits` (not public). Client IP from X‑Forwarded‑For with `TRUSTED_PROXY_HOPS` (default 2 — verified on this platform via `GET /api/admin/ip-check`).
- B‑3: `PUT /users/me/subscription` advisory (`subscription_source: self_reported`); admin stats labelled self‑reported + `rate_limited_requests`.
- Frontend: `results-rate-limited` state distinguishes temporary limits from Premium; admin limit inputs; results deep‑link redirect moved to effect.
- Tests: backend 160/160 (`test_phase_a_limits.py` 16 incl. concurrency, forged header, forged mirror, rotation, outage fail‑closed, expired→free, happy path with engine mocked); `tests/conftest.py` raises IP caps for the test runner's single IP during a session and restores. Frontend iterations 9–10 pass.
- Separate plan for genuine server‑side RevenueCat verification: `/app/memory/revenuecat_server_verification_plan.md` (not implemented).
- Rotate before production (values not recorded here): `JWT_SECRET`, `ADMIN_PASSWORD` (admin@datespark.app), test accounts `pa-*@example.com` created by tests.

## Date Spark 2.0 — Increment 5 · Phase 2: Real Travel Routing (2026‑06) ✅ built, flag OFF (not activated)
- Verified pricing: Routes "Compute Routes Essentials" (SKU 9EFF‑679A‑9B16) 10k free/mo then $5/1k (→$4/$3/$1.50/$0.38). Requests avoid Pro triggers (no routingPreference/optimizeWaypointOrder/≤10 intermediates). Transit = 1 call per leg; drive/walk = 1 call per spark.
- New `backend/routing.py`: provider abstraction, Mongo `route_cache` (7‑day TTL), `route_usage` daily cap (`ROUTES_DAILY_LIMIT`, default 300), per‑leg fallback. Legs carry `source`/`estimate`; spark `routing_source`. Flag `real_routing` default **False**; `GOOGLE_ROUTES_API_KEY` optional (falls back to Places key). No live calls made.
- UI: leg hint "Route via Google Maps" vs "Straight-line estimate — not a road, walking or transit route"; At‑a‑glance "· routed"; adaptive disclaimer. Admin row for real_routing.
- Tests: backend 143/143 (`test_real_routing.py` 23 — drive/walk/transit, cache hit/partial, 403/429/500/no‑route/malformed/timeout fallback, daily cap, no key, mixed, legacy legs, redaction, live flag‑off); frontend iteration 8 8/8.
- Activation checklist (pending user approval): enable Routes API on the Cloud project, add to key restrictions (or set GOOGLE_ROUTES_API_KEY), set console per‑day quota (~400) + $5 budget alert, then flip `real_routing` in admin.

## Date Spark 2.0 — Increment 5 · Phase 1: Venue Reliability (2026‑06) ✅
- Flag `features.venue_hours` (default on, admin row). Places field mask += `businessStatus`, `currentOpeningHours`, `utcOffsetMinutes` (same SKU tier — no new cost/credentials). New `backend/hours.py`: per‑stop `hours_status {status: open|closed|closed_permanently|closed_temporarily|unknown, confidence: confirmed (Google 7‑day window)|regular|none, detail}`; spark `hours_summary`. Engine drops CLOSED_* venues from candidates (never empties list), gives the model `hours_on_plan_day`, appends an hours rule to the system prompt only when flag on. Bug fix: `when_text` now renders the plan time in venue‑area local time (was UTC → "Sunday 12:00 AM" for a 7 PM Saturday plan).
- UI: Timeline badges ("Open at this time" / "Closed at this time" / "Usually closed…" / "Regular hours — confirm closer to the date" / "Hours not verified" / "Permanently|Temporarily closed"), At‑a‑glance `hours-summary` row, SparkCard closed‑stop warning, disclaimer about holidays. Independent of `experience_output` (CostSummary `showCosts`/`showHours`).
- Tests: backend 121/121 (`test_venue_hours.py` 23: open/closed/overnight/24h/missing/timezone/no‑date/beyond‑window/flag off byte‑identical/Places failure/locked recipient/legacy); frontend iteration 7 9/9.
- Decisions recorded: Routes API NOT enabled (`real_routing` not built); weather deferred; events research only. Phase 2 awaits approval — see `/app/memory/increment5_plan.md`.

## Date Spark 2.0 — Increment 4: Experience Output Upgrade (2026‑06) ✅
- Flag `features.experience_output` (default on, admin switch + tappable label rows `admin-flag-<id>-row`; PUT /admin/config merges flags key‑by‑key). OFF = original Timeline/SparkCard/results header.
- Spark detail: ordered itinerary with per‑stop duration (from start/end), travel connector between stops ("🚶 Walk ~2 min · 0.1 mi — Straight‑line estimate — not a road, walking or transit route"), "Price not listed" for unpriced stops, "At a glance" card (est. total, est. per person when party size known, "X of Y stops priced" warning, travel total, disclaimer), party‑size/transport chips. Surprise: owner sees legs only between revealed stops; locked recipient gets legs/costs stripped server‑side (`redact_for_recipient`), `/shared/{id}` exposes output + plan‑input fields.
- Results: `results-summary-chips` (budget/amount, location·distance, when, party size, duration, transport) + SparkCard glance line "3 stops · ~5 min travel · $84 total ($14/person)".
- New files: `frontend/src/plan.ts`, `frontend/src/components/CostSummary.tsx`, `backend/tests/test_experience_output.py`. Tests: backend 99/99, frontend iteration 6 8/8 (admin UI flag toggling, output ON/OFF, all‑flags‑OFF legacy Couple flow, surprise owner/recipient privacy).
- Not included (by design): weather, events, routing APIs, reservations, payments, marketplace. Awaiting approval before Increment 5.

## Date Spark 2.0 — Increment 3 verification pass (2026‑06) ✅
- Flag init fix: `useFeatures()` returns `ready`; Step 1–4 screens render `FeaturesLoading` until `/config/public` settles (no flash of Builder/Profiles UI when OFF). Who header shows 1/5 when builder ON.
- Engine influence proven: `tests/test_builder_engine_influence.py` — LLM prompt captured (experience_details carries party_size/budget_amount/duration_hours/interests/transport/scheduled_at, `when` has weekday, SURPRISE_ME mode) + live generation (interest "Tacos" surfaces, walk legs, per‑person = total/party_size, duration ≤ window). Backend 91/91.
- Frontend iteration 5: flag OFF → original 4‑step flow, flag ON → 5‑step builder flow, no‑flash poll, tabs/admin regression — all pass. Flags left ON.
- Increment 4 NOT started (awaiting authorization).

## Date Spark 2.0 — Increment 3: Experience Builder (2026‑06) ✅
- Flag `features.experience_builder` (default on, admin switch, independent of profiles). Step 1: party‑size stepper (non‑Couple; defaults couple 2/friends 4/family 4/celebration 6/travel 2/solo 1), "🎲 Surprise me" preference card (skips Vibe step, no transport), profile‑row edge fade. Vibe: collapsible profile‑aware interests chips. Budget: exact amount + $50/100/150/250 quick chips (tier kept in sync via `tierForAmount`). Distance CTA → Continue. New Step 5 `create/when.tsx`: date/time chips (→ `scheduled_at`), duration chips, transport chips. `results.tsx` sends only supplied fields. Engine: `when_text()` formats scheduled_at (weekday/time) for hours‑aware planning. `surprise_me` no longer derives a profile (profile from company/occasion).
- Tests: backend 86/86 (`test_experience_builder.py` new), frontend iteration 4 9/9 + manual flag‑off verification.
- Next: Increment 4 (engine output upgrade: travel legs, cost summary, Adjust sheet) after user review.

## Date Spark 2.0 — Increment 2: Experience Profiles (2026‑06) ✅
- Profiles: Couple (original flow, untouched) · Friends · Family · Celebration · Travel · Solo as a chip row on Step 1 (`(tabs)/create.tsx`), gated by `app_config.features.experience_profiles` (default on, admin switch). Profiles narrow/pre‑fill the existing "who" cards; `solo` relationship added; Travel relabels the location title. `experience_type` sent only for non‑Couple profiles. "Surprise me" remains a planning mode, not a profile.
- Tests: backend 62/62 (new `test_experience_profiles.py`), frontend iteration 3 all pass.
- Next: Increment 3 (Experience Builder inputs) after user review.

## Date Spark 2.0 — Increment 1: Engine Foundation (2026‑06) ✅
- Backend only, zero UI change. `GenerateIn` gained optional `experience_type, party_size, budget_amount, duration_hours, interests[], transport, scheduled_at, surprise_me` (vibes required unless surprise_me). Engine: `resolve_mode()` (SURPRISE > OCCASION > SURPRISE_ME > NORMAL), `compute_travel_legs()` (haversine, walk/transit/drive speeds), `cost_rollup()` (never invents prices), `parse_cost()`. Sparks store the new fields + `travel_legs`, `total_travel_minutes/miles`, `total_estimated_cost`, `per_person_cost`, `priced/unpriced_stops`, `complete`. `server.py` not split (not needed).
- Tests: `backend/tests/test_engine_foundation.py` (21) + existing 22 → 43/43 pass.
- Next: Increment 2 (Experience Profiles UI) after user review.

## Android versionCode set to 104 (2026-06) — package com.date_spark.myapp unchanged.
