# Real Routing — Operational Verification & Activation Checklist (Increment 5 · Phase 2)

Status: built, tested, **flag `real_routing` OFF**. No Google Routes requests have been made from this codebase.

## 1. SKU & pricing (verified against developers.google.com/maps/billing-and-pricing/pricing, "Last updated 2026‑10‑07")
- SKU: **Routes: Compute Routes Essentials** — ID `9EFF-679A-9B16`.
- Free usage cap: **10,000 billable events / month**. Then per 1,000: **$5.00** (cap–100k) · $4.00 (100k–500k) · $3.00 (500k–1M) · $1.50 (1M–5M) · $0.38 (5M+).
- Our request shape stays on Essentials: `travelMode` DRIVE/WALK/TRANSIT, ≤10 intermediates (we send ≤3), **no** `routingPreference`, **no** `optimizeWaypointOrder`, **no** side‑of‑road/heading/vehicle‑stopover modifiers, field mask limited to `routes.legs.distanceMeters,routes.legs.duration`. Any of the excluded features would re‑rate the request to *Compute Routes Pro* ($10/1k, 5,000 free).
- Free allowance scope: the cap is **per SKU, per month, per billing account**. Google states usage is "aggregated for all projects linked to the customer billing account" to determine the tier, so **other projects on the same billing account that call Compute Routes Essentials share the 10,000**. Places SKUs have their own separate caps and do not consume it.

## 2. Daily cap `ROUTES_DAILY_LIMIT` (default 300)
- Enforced **server‑side in Mongo**, not in process memory: `route_usage` document per UTC day, incremented with an atomic `findOneAndUpdate($inc, upsert)` before every provider call. Operational test: 120 concurrent reservations against a limit of 50 → exactly 50 allowed, 70 denied; a second client (simulating another worker / a restart) read the same counter and was denied. Counter survives restarts and is shared by all workers.
- Reset: keyed by UTC calendar day — a new day starts a new counter at 0. Old day documents are tiny and kept for audit.
- Counting is conservative: an attempt is counted even if Google returns an error, so our counter can only over‑estimate billable usage.
- Limit value is read from the environment on every call; if unset or invalid → 300. Production must set `ROUTES_DAILY_LIMIT` in the deployment environment if a different value is wanted.
- **Fail‑closed**: if the counter or cache is unavailable (DB error) `reserve_call()` returns False → no provider call → straight‑line fallback. Generation is never blocked.

## 3. Cache
- Collection `route_cache`, shared across users and workers, TTL index on `created_at` (7 days), unique `key`.
- Key = `fromVenueId|toVenueId|mode|transitHourBucket` (coordinates used when a venue id is absent). Direction, travel mode and — for transit only — the departure hour (UTC) are part of the key; drive/walk legs carry no departure component because requests are traffic‑unaware (Essentials). Far‑future transit (>7 days) is requested without `departureTime`, so its cache bucket is empty and consistent with the request made.
- A cached leg is reused only when all key parts match; cached legs keep `source: google_routes`.

## 4. Failure behaviour (all covered by automated tests, provider stubbed)
| Condition | Result |
|---|---|
| No `GOOGLE_ROUTES_API_KEY` / `GOOGLE_PLACES_API_KEY` | provider skipped; straight‑line legs |
| 403 (API not enabled / key restricted) | logged once per call; straight‑line legs |
| 429 (quota / rate limit) | straight‑line legs |
| 5xx, no route, malformed response, timeout | straight‑line legs |
| Daily cap reached | straight‑line legs |
| Transit gap on one leg | that leg straight‑line, others routed → `routing_source: mixed` |
Every fallback leg carries `source: straight_line`, `estimate: true`, and the UI prints "Straight‑line estimate — not a road, walking or transit route". Spark generation never fails because of routing.

## 5. Tests (final code)
- Full backend suite re‑run on the final tree: see `/app/test_reports/pytest/increment5_phase2_final.xml`.
- `tests/test_real_routing.py`: 16 functions / 22 cases, provider stubbed at `routing._post` — **no Google Routes traffic**.
- Tests that use live external services (existing ones, not Routes): generation tests across suites call the deployed backend → Claude (Emergent key) and Google Places (existing key). Two routing tests hit the live API only to assert the flag is OFF and output is straight‑line.
- Frontend: iteration 8 (8/8) on the final frontend code.

## 6. Google Cloud Console steps (no secrets in this document)
1. **Select the project** that owns the current Places key (Console → project picker).
2. **Enable the API**: APIs & Services → Library → search "Routes API" → Enable.
3. **Create a dedicated server key** (keep the Places key untouched): APIs & Services → Credentials → Create credentials → API key → rename `datespark-server-routes`.
   - Application restrictions: *IP addresses* if the backend egress IP is static; otherwise *None* (server‑side only — never ship this key in the app).
   - API restrictions: *Restrict key* → select **Routes API** only → Save.
4. **Set quotas**: APIs & Services → Enabled APIs → Routes API → Quotas & System Limits → edit "Compute Routes requests per day" → **400** (and optionally per‑minute → 60). This is Google's hard stop above our 300/day app cap.
5. **Budget alert**: Billing → Budgets & alerts → Create budget → scope: this project → amount **$5** → thresholds 50 / 90 / 100 % → email recipients → Finish.
6. **Monitor**: Billing → Reports → filter SKU "Routes: Compute Routes Essentials"; APIs & Services → Routes API → Metrics.
7. **Hand‑over**: paste the new key only into the deployment's environment variables as `GOOGLE_ROUTES_API_KEY` (not in chat, not in logs). Optionally set `ROUTES_DAILY_LIMIT`.

## 7. Activation sequence (after your explicit approval)
1. Env var present → restart backend.
2. Admin → toggle **Real Routing** ON → Save (`real_routing` flag).
3. Generate one plan; confirm a leg shows "Route via Google Maps" and `routing_source: google_routes`; confirm `route_usage` counter incremented by the expected 1–3 calls.
4. Check Billing report next day: usage inside the free cap. Rollback = flip the flag OFF (instant, no redeploy).
