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
