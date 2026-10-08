# Date Spark — Current State Assessment & 2.0 Migration Plan
_Generated 2026‑06 · No code changes made._

## 1. Architecture (as built)
- **Mobile:** Expo SDK 54 · expo‑router (file routing) · TanStack Query · Reanimated · react‑native‑keyboard‑controller · theme tokens in `src/theme.ts` (warm coral palette, Outfit + Plus Jakarta Sans). Runs on iOS/Android/web preview. ~4.7k LOC total.
- **Backend:** FastAPI (`backend/server.py`, 820 lines) + Motor/MongoDB. Modules: `recommend.py` (AI engine), `places.py` (venue/geocode provider layer). All routes under `/api`.
- **Identity model:** guest‑first. Every record carries `owner_type` (`guest|user`) + `owner_id`. Guests use header `X-Guest-ID`; accounts use a 30‑day HS256 JWT. On signup/login/Google/Apple the guest's sparks, saves and events are migrated to the user (`migrate_guest`).
- **Premium gating:** client‑side via RevenueCat entitlement `pro`; client sends `X-Premium: 1` which bypasses the monthly free limit. Backend mirrors status to `users.subscription_status` for reporting only.

## 2. Screens & flows (17 routes)
| Route | Purpose | Reuse in 2.0 |
|---|---|---|
| `index` | Welcome (Create a Spark, Google, Log In, Explore) | ✅ keep |
| `(tabs)/home` | Hero CTA, 4‑step explainer, promo + free usage, featured, recent | 🔧 extend (modes, upcoming, Spark of the week) |
| `(tabs)/create` | Step 1 Who + occasion chips (Premium) | 🔧 extend (mode entry) |
| `create/vibe` · `budget` · `distance` | Steps 2–4; location via GPS or city/ZIP; Surprise toggle (Premium) | ✅ keep |
| `create/results` | 3 AI Spark cards, regenerate, empty‑state fixes, 402 → paywall | ✅ keep |
| `spark/[id]` | Detail: map, chips, why, itinerary timeline, save, complete, surprise reveal, recipient "I'm in", add‑to‑calendar | 🔧 extend |
| `share/[id]` | Spark It: date/time chips → `scheduled_at`, invitation text, native share / copy, calendar | 🔧 extend (RSVP) |
| `(tabs)/sparks` | My Sparks: Saved / Created / Completed | 🔧 extend (Memories) |
| `(tabs)/profile` | Account, stats, favorite vibes, premium card, admin link, logout, delete | 🔧 extend |
| `auth` | Email/password + Google + Apple (iOS) | ✅ keep |
| `premium` | Paywall, RevenueCat package, restore, confirm sheet | ✅ keep |
| `admin` | Stats grid + lists + config form | 🔧 extend |

Wizard state lives in `src/wizard.tsx` (relationship, vibes, budget, distance, location, occasion, surprise, results, seenTitles, usage).

## 3. Database (MongoDB, 7 collections)
| Collection | Key fields | Notes |
|---|---|---|
| `users` | id, name, email (unique), password_hash?, apple_sub (sparse unique), google_linked, picture, role, location, subscription_status/start/end, created_at, deleted_at | soft delete |
| `user_preferences` | owner_type/owner_id, relationship_preferences, favorite_vibes, budget_preferences, distance_preferences | guest‑capable |
| `sparks` | id, owner_*, title, emoji, tagline, description, primary_vibe, vibe_tags, estimated_cost/duration, why, dress_code, **activities[] (embedded SPARK_ACTIVITIES)**, location_label, distance_miles, lat/lng, needs_verification, relationship_type, vibe[], budget, distance, location, date_label, time_label, scheduled_at, occasion, surprise, revealed_steps, status (generated/scheduled/sparked/completed), share_count, created_at, completed_at, deleted_at | spec's SPARK_ACTIVITIES is embedded, not a separate collection (fine for 2.0) |
| `saved_sparks` | owner_*, spark_id, created_at, deleted_at | upsert, soft delete |
| `subscriptions` | user_id, plan, status, provider, renewal_date, start_date | reporting mirror |
| `analytics_events` | event, owner_*, props, created_at | all spec events + spark_accepted, surprise_step_revealed |
| `app_config` | key=main, free_spark_limit, premium_price, trial_days, promo_message, featured_experiences[], ai_settings{model, guidance} | admin‑editable |

IDs are UUID strings; `_id` always excluded from responses.

## 4. API surface (27 endpoints)
- Public config/geo: `GET /config/public`, `GET /places/geocode`
- Auth: `POST /auth/signup|login|session(Google)|apple`, `GET /auth/me`, `DELETE /auth/account`
- Profile: `PUT /users/me`, `GET|PUT /users/me/preferences`, `PUT /users/me/subscription`
- Sparks: `GET /sparks/usage`, `POST /sparks/generate`, `GET /sparks/mine`, `GET /sparks/{id}` (owner/recipient‑aware), `GET /shared/{id}` (public, redacted), `PUT /sparks/{id}/reveal|schedule`, `POST|DELETE /sparks/{id}/save`, `POST /sparks/{id}/share|complete`
- Analytics: `POST /events`
- Admin: `GET /admin/stats`, `GET|PUT /admin/config`

## 5. Integrations
| Integration | Implementation | Health |
|---|---|---|
| **Claude Sonnet 4.6** (Emergent key, `emergentintegrations`) | `recommend.py`: system prompt with recommendation principles; context = who/vibes/budget/radius/location/when/history/avoid‑titles/admin guidance/mode (NORMAL · OCCASION · SURPRISE); venues passed as `venue_id` list; strict JSON; post‑processing attaches real venue data, flags `needs_verification` | ✅ working; one LLM call per generation (~20–40s) |
| **Google Places API (New)** | `places.py` `search_venues` (text search w/ locationBias, field mask incl. hours, price level, rating, maps URL) + `geocode`; vibe → query map (`VIBE_QUERIES`); Nominatim fallback | ✅ enabled & returning real venues |
| **RevenueCat (Emergent‑managed)** | `src/revenuecat.tsx` provider (customer info, offerings, purchase, restore), identity bound to user id in `session.tsx`; product `$rc_monthly` $24.99 / P1M / 2‑week trial, `$rc_annual` $79.99; Test Store in preview | ✅ provisioned; store‑side credentials still to be uploaded by you for real purchases |
| **Auth** | pwdlib/argon2 passwords, PyJWT; Emergent Google (`/auth/session`); Apple JWKS verification (`APPLE_AUDIENCES`) | ✅ |
| **Device** | expo‑location (contextual permission + manual city/ZIP + Settings deep link), expo‑calendar (alerts 1h / 1d), RN Share, expo‑clipboard, react‑native‑maps (native) / placeholder (web) | ✅ permission contract followed |

## 6. Permissions (`app.json`)
iOS: location when‑in‑use, calendars (full + write‑only), Apple Sign‑In entitlement. Android: ACCESS_COARSE/FINE_LOCATION, READ/WRITE_CALENDAR. Scheme `datespark`. Bundle `com.emergent.vibefinder.rvztki` · package `com.date_spark.myapp` · versionCode 104.

## 7. Known gaps / tech debt (relevant to 2.0)
1. Premium enforcement is client‑trusted (`X-Premium` header). Fine for MVP; 2.0 should verify entitlement server‑side (RevenueCat webhook → `subscriptions`) if revenue‑critical features move to the backend.
2. `subscription_cancelled` event not tracked (needs RevenueCat webhook).
3. Spark imagery is 3 static Unsplash photos cycled; no per‑experience imagery.
4. No invitee identity: recipient "I'm in" saves to their own account but the planner isn't notified (no RSVP state on the spark).
5. One monolithic `server.py`; splitting into routers (`auth`, `sparks`, `admin`) is cheap and recommended before adding 2.0 modules.
6. Light theme only (theme tokens support dark; values not filled).
7. Free‑limit counting uses `analytics_events` (`sparks_generated` per month) — works, but a dedicated `usage` counter is cleaner.

## 8. What 2.0 can reuse as‑is
Guest‑first identity + migration · wizard framework + option components · AI engine & provider layer (add new modes by extending `mode` and prompt) · spark/share/detail screens · RevenueCat provider and paywall · admin config pattern (`app_config`) · analytics tracker · design system (theme, Button, Chip, OptionCard, StepHeader, Toast, StickyFooter, Timeline, SparkCard).

## 9. Proposed migration plan (incremental, no rewrite)
**Phase 0 — Foundations (1 session)**
- Split `server.py` into routers; add `usage` counter; add RevenueCat webhook → server‑side entitlement + `subscription_cancelled`.
- Add `spark_participants` collection (spark_id, owner_*, role planner|invitee, rsvp, joined_at) to unlock RSVP/couples/group features.

**Phase 1 — Connection modes (Couples / Family / Friends / Group)**
- Extend wizard step 1 into "modes" that pre‑tune vibes/budget prompts and unlock mode‑specific prompts (e.g., Family → kid‑friendly flags; Group → headcount + split cost).
- Backend: `mode` field on sparks; `VIBE_QUERIES` per mode; prompt branch. Reuses everything else.

**Phase 2 — RSVP + shared planning**
- Invitee "I'm in" writes `spark_participants`; planner sees RSVP status on detail + My Sparks; invitee can propose a time (`PUT /sparks/{id}/propose`).
- Group planning: multiple invitees, simple vote on 3 Sparks.

**Phase 3 — Date history & memories**
- After `complete`, add photo + note (Emergent Object Storage) → `spark_memories`; "Memories" section in My Sparks; relationship milestones derived from history.

**Phase 4 — Event discovery & local partners**
- New provider in `places.py` for events (e.g., Ticketmaster/Eventbrite) feeding the venue list; `featured_experiences` becomes sponsored/partner experiences with admin management; reservations/tickets via deep links first.

**Phase 5 — Personalization & growth**
- "Spark of the week" (scheduled generation per user prefs), AI special‑occasion suggestions from history, gift Sparks, dark theme, per‑vibe imagery.

Each phase ships independently, keeps all current screens working, and only adds fields/collections (no destructive migrations).
