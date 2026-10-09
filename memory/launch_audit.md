# Date Spark — Launch Readiness Audit (read‑only, 2026‑06)

No code, flags, deployments or builds were changed. No live billing calls were made.

## Summary
- **3 BLOCKERS**, **9 IMPORTANT**, **8 LATER**.
- Core experience is functionally complete and well covered by automated tests (backend 143/143, frontend iterations 4–8 all pass).
- The blockers are about **money and store compliance**, not features: Premium is asserted by the client, the free quota is trivially evaded, and the paywall lacks the legal links Apple/Google require.

---

## A. Core experience — VERIFIED ✅
| Area | Evidence | Status |
|---|---|---|
| Six profiles | `EXPERIENCE_PROFILES` in `constants.ts`; iteration 4/5 tests (Family, Friends, Solo, Couple); `test_experience_profiles.py` | ✅ |
| Surprise Me / Surprise gift | iteration 4 (Surprise Me skips Vibe; transport hidden), iterations 6–8 (owner/recipient privacy) | ✅ |
| Experience Builder | iteration 5 flag ON/OFF, no-flash; `test_experience_builder.py`, `test_builder_engine_influence.py` (inputs change the prompt + output) | ✅ |
| Itinerary output | iteration 6 (durations, legs, cost, chips); `test_experience_output.py` | ✅ |
| Venue hours | iteration 7; `test_venue_hours.py` (23 cases) | ✅ |
| Cost summaries | per-person only with party size; unpriced stops surfaced; never invented | ✅ |
| Travel fallback | `test_real_routing.py`: 403/429/5xx/timeout/no‑route/cap/no key → labelled straight-line; `real_routing` OFF | ✅ |
| Legacy Couple flow with all flags OFF | iterations 5, 6, 7 | ✅ |

Unverified: behaviour on **real iOS/Android devices** (all UI tests ran on the web preview). See D‑4.

---

## B. Accounts & subscriptions
| # | Finding | Class | Evidence | Next action |
|---|---|---|---|---|
| B‑1 | **Premium is client‑asserted.** `/api/sparks/generate` treats header `X-Premium: 1` as proof of Premium (`server.py` L561‑567). Anyone can add the header and get unlimited generations (each costs Claude + up to 6 Places Enterprise calls). | **BLOCKER** | `is_premium = x_premium == "1"` | Verify entitlement server‑side: RevenueCat webhook → `subscriptions` collection (already exists as a mirror) and/or server‑to‑RevenueCat customer lookup via the integration proxy; ignore the header. |
| B‑2 | **Free quota evadable.** Usage is counted per `X-Guest-ID`; a client can rotate the id for unlimited free sparks. | **BLOCKER** (cost) | `identity()` L244‑252, `usage_for()` | Add server‑side rate limiting per IP/device (e.g. N generations/hour) and cap guest ids per IP; consider requiring sign‑in after the first free spark. |
| B‑3 | Subscription mirror `PUT /users/me/subscription` is written by the client, not by RevenueCat. Admin stats (conversion rate) therefore trust the client. | IMPORTANT | L504‑528 | Replace with RevenueCat webhook (same fix as B‑1). |
| B‑4 | RevenueCat: project, entitlement `pro`, offering `default`, monthly $24.99 (2‑week trial) configured; app uses `EXPO_PUBLIC_REVENUECAT_*` keys. **Unverified**: store‑side products (App Store Connect / Play Console IAPs with matching product ids), App Store Connect API key and Play service‑account upload in the RevenueCat dashboard, and a real purchase on device. | IMPORTANT | `memory/revenuecat.md`, `src/revenuecat.tsx` | Complete the store steps listed in revenuecat.md; test with TestFlight / Play internal testing; verify “Restore Purchases”. |
| B‑5 | Annual package `$rc_annual` exists in RevenueCat but is not shown in the paywall. | LATER | revenuecat.md | Decide whether to surface it. |
| B‑6 | Auth: JWT 30‑day tokens, pwdlib hashing with dummy‑hash timing protection, Apple JWKS verification, Emergent Google session exchange, soft‑delete account — sound. **No brute‑force throttling** on `/auth/login`. | IMPORTANT | L362‑370 | Add per‑IP/per‑email attempt limiting (or lockout) before launch. |
| B‑7 | Password reset / “forgot password” flow does not exist. | IMPORTANT | no route in `server.py`; no screen | Add reset (email via Emergent Resend) or clearly route users to Apple/Google sign‑in. |

---

## C. Privacy & security
| # | Finding | Class | Evidence | Next action |
|---|---|---|---|---|
| C‑1 | Secrets live only in `backend/.env` (LLM key, JWT secret, admin password, Places key); never sent to the client. Frontend `.env` holds only RevenueCat **public** SDK keys (safe by design). | ✅ | `.env` inspection (values not printed) | Ensure production env vars are set in the deployment panel; rotate `JWT_SECRET`/admin password for production. |
| C‑2 | Surprise redaction: locked recipients get `activities: []`, legs `[]`, costs/hours/routing `None`; only meet time/place. Covered by tests in 4 suites + iterations 6–8. | ✅ | `redact_for_recipient()` | — |
| C‑3 | Server‑side validation: Pydantic models with bounds (password 8–128, party_size, budget_amount ≤ 100k, config fields ≥0 ≤1000, guest id 8–64). Admin routes require `role == admin`. | ✅ | `GenerateIn`, `ConfigUpdate` | — |
| C‑4 | `CORS allow_origins=["*"]` with `allow_credentials=True`. Harmless for bearer‑token mobile apps, but overly broad for the web build. | LATER | L901 | Restrict to the production web origin(s). |
| C‑5 | Shared links: any spark is readable by UUID via `/shared/{id}` and `/sparks/{id}` (non‑owner redacted view). UUIDs are unguessable, so acceptable for an invite feature; but sparks of **deleted accounts** stay reachable via existing links. | LATER | L726‑734 | Filter `deleted_at` in `/shared` and `/sparks/{id}`. |
| C‑6 | Admin seeded from env on startup; credentials in `memory/test_credentials.md`. | IMPORTANT | | Change `ADMIN_PASSWORD` in production env and remove the file’s password from any shared artefacts. |
| C‑7 | Analytics events store guest ids + plan props (no PII beyond email on users). Account deletion anonymises user + soft‑deletes sparks. | ✅ | `delete_account` | Document in privacy policy; see E‑2. |

---

## D. Production readiness
| # | Finding | Class | Evidence | Next action |
|---|---|---|---|---|
| D‑1 | **No request timeouts** around the Claude call (`recommend.py`) or in the frontend `api()` fetch; a hung LLM call leaves the results screen on “Designing your moment…” indefinitely. | IMPORTANT | no `asyncio.wait_for`/`AbortController` | Add `asyncio.wait_for(…, 120s)` server‑side → 504 with a friendly message; frontend abort + “Try again” after ~120 s. |
| D‑2 | `iOS bundleIdentifier` is still the generated placeholder `com.emergent.vibefinder.rvztki` while Android is `com.date_spark.myapp`. RevenueCat’s Apple app record must match whatever is used for the App Store record. | IMPORTANT | `app.json` | Decide the final iOS bundle id **before the first iOS build**, update `app.json` and the RevenueCat Apple app. |
| D‑3 | `expo.version` is `1.0.0`, `versionCode` 104; no `ios.buildNumber`. | LATER | `app.json` | Set `ios.buildNumber` and keep versions in sync at release time. |
| D‑4 | All UI verification used the **web preview**; native‑only paths (RevenueCat purchase, Apple Sign‑In, calendar write, location permission dialogs) are untested on devices. Permission handling follows the contract (`canAskAgain`, Open Settings — 8 references). | IMPORTANT | iteration reports | Run one TestFlight + one Play internal build through: sign‑in (Apple/Google/email), generate, surprise share, calendar add, purchase + restore. |
| D‑5 | No frontend request retry/offline messaging beyond TanStack defaults; `identityError` banner exists for guest‑id failure. | LATER | `session.tsx` | Add offline toast on generate failure. |
| D‑6 | Logging: provider failures logged as warnings (good); no structured request logging / alerting for 5xx. | LATER | | Hook deployment logs to alerts post‑launch. |
| D‑7 | Admin dashboard, invite share, calendar, map all complete; no unfinished screens or TODOs found (`grep TODO|FIXME|coming soon` → none). | ✅ | | — |

---

## E. Store readiness
| # | Finding | Class | Evidence | Next action |
|---|---|---|---|---|
| E‑1 | **Paywall lacks Terms of Use (EULA) and Privacy Policy links.** Apple Guideline 3.1.2 requires both on the subscription screen with price, period and trial terms; Google Play Billing policy requires clear pricing/trial disclosure. | **BLOCKER** (store rejection) | no `Privacy/Terms/Linking.openURL` in `premium.tsx`/`profile.tsx` | Host a privacy policy + terms page; add links on Premium screen and Profile; state “$24.99/month after 2‑week free trial, cancels anytime”. |
| E‑2 | Privacy policy URL is required in App Store Connect and Play Console (Data safety form: location, email, purchase history, analytics/usage). | IMPORTANT | | Write the policy; fill Data safety / App Privacy questionnaires. |
| E‑3 | Google Play: `targetSdk` comes from Expo SDK 54 (API 35 ✔), permissions declared (location, calendar) with rationale strings ✔, package `com.date_sp ark.myapp` ✔, versionCode 104 ✔. Outstanding: store listing assets (icon 512, feature graphic, screenshots), content rating, Data safety, IAP products, closed‑testing requirement for new personal developer accounts (12 testers / 14 days). | IMPORTANT | `app.json` | Prepare assets + listing; create the IAP product id from revenuecat.md; run closed test. |
| E‑4 | iOS: Sign in with Apple ✔ (required because Google login is offered), account deletion ✔, `ITSAppUsesNonExemptEncryption=false` ✔, usage strings ✔. Outstanding: Apple Developer account, final bundle id (D‑2), App Store listing, App Privacy answers, IAP product + Paid Apps agreement, TestFlight run, review notes with a demo login. | IMPORTANT | `app.json` | Complete via the Emergent Publish flow. |
| E‑5 | Splash/icon assets present; app name “Date Spark”. Ensure trademark/name availability on both stores. | LATER | | Check listing name availability. |

---

## F. Testing
- **Backend**: 143/143 (`/app/test_reports/pytest/increment5_phase2_final.xml`) — includes legacy flows, every feature flag, surprise redaction, hours edge cases, routing fallbacks. Live tests call Claude + Places through the deployed backend; **none call Google Routes**.
- **Frontend**: iterations 4–8 all green (builder, output, hours, routing labels, admin flag UI, surprise privacy, legacy Couple).
- **Not covered by automation (IMPORTANT to cover manually before launch)**:
  1. Real purchase, trial start, renewal/cancel → Premium gate (402) on device.
  2. Apple Sign‑In and Google sign‑in on device; guest → account migration of sparks.
  3. Calendar add + reminder; deep link `datespark://spark/{id}` opening the app from a shared message.
  4. Location permission denied → manual city entry path.
  5. Monthly free‑limit rollover; 402 paywall redirect when limit reached.
  6. Network loss / LLM timeout during generation (see D‑1).
  7. Accessibility: only 1 `accessibilityLabel` in the codebase (LATER).

---

## G. Cost risks & safeguards (no live calls made)
| Service | Trigger | Current safeguard | Gap |
|---|---|---|---|
| **Google Places Text Search (Enterprise SKU, ~$35/1k after 1,000 free)** | up to 6 calls per generation | none beyond free limit (which is evadable — B‑1/B‑2) | **Highest exposure.** Rate‑limit generation; consider Pro‑tier search + selective details (two‑step) to cut cost ~5×. |
| **Claude Sonnet 4.6 via Emergent LLM key** | 1 call per generation | Emergent key balance (top‑up/auto‑top‑up) | Same evasion gap; add rate limiting. |
| Google Routes | none — flag OFF, no key configured | daily cap 300, 7‑day cache, fail‑closed | Activation checklist pending approval. |
| Nominatim (OSM) geocode fallback | geocode only | free; usage policy requires attribution/low volume | LATER: add attribution or move to Places geocoding. |
| RevenueCat | free up to $2.5k MTR | — | — |
| Mongo | storage | 317 sparks today | fine |

---

## Recommended order before launch
1. **B‑1 + B‑2** server‑side entitlement + rate limiting (closes the cost hole).
2. **E‑1 / E‑2** privacy policy + terms, paywall disclosures.
3. **D‑2** final iOS bundle id; **B‑4** store IAP setup; **D‑1** timeouts; **B‑6** login throttling; **B‑7** password reset decision.
4. Device test pass (D‑4) via TestFlight / Play internal testing, then store listings (E‑3/E‑4).
5. LATER items post‑launch.
