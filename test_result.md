#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================
## Verification pass — Increment 3 (2026-06, main agent)
- Fixed feature-flag initialization: `src/features.ts` now exposes `ready`; `(tabs)/create.tsx`, `create/vibe.tsx`, `create/budget.tsx`, `create/distance.tsx` render `FeaturesLoading` (testIDs `create-*-loading`) until `/api/config/public` settles, so Builder/Profiles UI can never flash when a flag is OFF. Who-step header now shows 1/5 when builder is ON.
- New backend tests `tests/test_builder_engine_influence.py` (prompt capture with LLM mocked + live generation). Full suite 91/91.
- Needs frontend E2E: builder flag OFF (via PUT /api/admin/config as admin) restores original 4-step flow; ON restores 5-step flow; no loading spinner stuck; legacy Couple flow intact. Flags must be left ON at the end.

## Increment 4 — Experience Output Upgrade (2026-06, main agent)
- New flag `features.experience_output` (default ON; admin switch `admin-flag-experience-output`; label-tap rows `admin-flag-<id>-row` toggle flags without the RN-web Switch). PUT /api/admin/config now merges feature flags key-by-key.
- Spark detail (`app/spark/[id].tsx`): enriched Timeline (per-stop duration `itinerary-step-N-duration`, travel connector `itinerary-leg-N` labelled straight-line estimate, `itinerary-step-N-unpriced`), `cost-summary` card (`cost-total`, `cost-per-person`, `cost-unpriced`, `travel-total`, `estimate-disclaimer`), chips `chip-party-size`, `chip-transport`. Surprise owner: only legs between revealed stops; locked recipient: backend strips legs/costs.
- Results (`app/create/results.tsx`): `results-summary-chips` with `results-chip-{budget,location,when,party,duration,transport}` replaces the plain summary line when flag ON; SparkCard `spark-card-N-glance` line.
- Flag OFF → original Timeline/SparkCard/results header. Backend 99/99.

## Increment 5 · Phase 1 — Venue Reliability (2026-06, main agent)
- New flag `features.venue_hours` (default ON; admin row `admin-flag-venue-hours-row` / switch `admin-flag-venue-hours`). Backend: Places field mask += businessStatus/currentOpeningHours/utcOffsetMinutes (same SKU, no new key); `hours.py` evaluates per-stop `hours_status {status, confidence, detail}`; spark `hours_summary`; closed venues dropped from candidates; `when_text` now rendered in venue-area local time.
- Frontend: Timeline badge `itinerary-step-N-hours` + text `itinerary-step-N-hours-text` ("Open at this time" / "Closed at this time" / "Usually closed at this time" / "Regular hours — confirm closer to the date" / "Hours not verified" / "Permanently closed" / "Temporarily closed"); At-a-glance `hours-summary` row; SparkCard `spark-card-N-hours-warning` when closed>0; disclaimer mentions holidays. Flag OFF → no badges/rows (Increment 4 UI unchanged). Independent of experience_output (CostSummary showCosts/showHours).
- Demo sparks (owner guest id `guest-hours-demo-02`): b50acd38-5411-4b6f-ae1f-25fb40f7d711 (2 confirmed open, 1 closed), b52e3c47-f107-460f-b99d-089ab92c1e11 (2 open, 1 unverified). Older spark b9c910be-cb10-4af9-a48d-f2e3e5616b46 (owner guest-a91990e00dd0) has NO hours fields (legacy).
- Backend 121/121.

## Increment 5 · Phase 2 — Real Travel Routing (2026-06, main agent) — flag OFF by default
- New `backend/routing.py`: Google Routes `computeRoutes` provider (Essentials SKU only), Mongo `route_cache` (7-day TTL) + `route_usage` daily cap (ROUTES_DAILY_LIMIT default 300), per-leg fallback to straight-line. `recommend.resolve_travel_legs()`; legs carry `source` ("google_routes"|"straight_line") + `estimate`; spark `routing_source` (google_routes|mixed|straight_line). Flag `features.real_routing` default **False**; admin row `admin-flag-real-routing-row` / switch `admin-flag-real-routing`.
- Frontend: Timeline leg hint `itinerary-leg-N-source` = "Route via Google Maps" (routed, no "~") or "Straight-line estimate — not a road, walking or transit route"; At-a-glance travel row adds "· routed" when all legs routed; disclaimer adapts (all routed / mixed / straight-line).
- UI demo sparks (synthetic DB docs, owner `guest-routing-demo`, no provider calls): /spark/demo-routed-0000-0000-000000000001 (both legs routed), /spark/demo-mixed-0000-0000-000000000001 (leg 0 routed, leg 1 straight-line). Real spark b50acd38 (owner guest-hours-demo-02) has straight-line legs only.
- Backend tests `tests/test_real_routing.py` (23) fully stubbed — zero Google Routes traffic.

## Phase A — Subscription security & cost protection (2026-06, main agent)
- `backend/limits.py` (new): atomic Mongo rate limiter (`rate_limits` coll., TTL) reserved BEFORE Claude/Places in POST /api/sparks/generate. Layers: per-IP hourly/daily, new-guest-ids-per-IP daily (rotation protection), identity ceilings — free monthly (existing free_spark_limit → 402) or, when `X-Premium: 1` is *claimed*, bounded premium ceilings (daily/monthly → 429). Fail-closed on limiter outage (429). Admin-tunable `app_config.limits` (admin inputs `admin-limit-<key>`); not in /config/public. Client IP from X-Forwarded-For with TRUSTED_PROXY_HOPS=2 (admin check `GET /api/admin/ip-check`).
- B-3: `PUT /users/me/subscription` advisory only (`subscription_source: self_reported`); admin stats labelled "(self-reported)", new `subscription_metrics_source`, `rate_limited_requests`.
- Frontend: results screen `results-rate-limited` state (title "Taking a short breather", message testID `results-rate-limited-message`, `results-rate-limited-back`), distinguishes temporary limit from Premium access.
- Tests: `tests/test_phase_a_limits.py` (20). To trigger a 429 in UI tests: PUT /api/admin/config {"limits":{"guest_ids_per_ip_daily":0}} then generate as a NEW guest → 429 pre-LLM; RESTORE to 20 afterwards (defaults: ip_hourly_cap 20, ip_daily_cap 80, guest_ids_per_ip_daily 20, premium_daily_cap 15, premium_monthly_cap 60).
