"""Iteration 11 — API verification: client X-Premium header must NOT exceed free quota.

Run as a standalone script (per request: skip pytest). Keeps total LLM generations ≤ 3.
"""
import os
import sys
import uuid
import json
import time
import requests

BASE = os.environ["SPARKS_TEST_BASE_URL"] + "/api"
ADMIN_EMAIL = os.environ["SPARKS_TEST_ADMIN_EMAIL"]
ADMIN_PASS = os.environ["SPARKS_TEST_ADMIN_PASSWORD"]

LOCATION = {"label": "Austin, TX", "lat": 30.2672, "lng": -97.7431}
GEN_BODY = {
    "relationship_type": "partner",
    "vibes": ["fun"],
    "budget": "25-50",
    "distance": "10",
    "location": LOCATION,
}

DEFAULT_LIMITS = {
    "ip_hourly_cap": 20,
    "ip_daily_cap": 80,
    "guest_ids_per_ip_daily": 20,
    "premium_daily_cap": 15,
    "premium_monthly_cap": 60,
}


def jp(label, resp):
    try:
        body = resp.json()
    except Exception:
        body = resp.text[:300]
    print(f"[{label}] HTTP {resp.status_code} :: {json.dumps(body)[:500] if isinstance(body, (dict, list)) else body}")
    return resp


def admin_token():
    r = requests.post(f"{BASE}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASS}, timeout=30)
    jp("admin login", r)
    r.raise_for_status()
    j = r.json()
    return j.get("access_token") or j.get("token")


def get_config(tok):
    r = requests.get(f"{BASE}/admin/config", headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def put_config(tok, patch):
    cur = get_config(tok)
    body = {
        "free_spark_limit": cur["free_spark_limit"],
        "premium_price": cur["premium_price"],
        "trial_days": cur["trial_days"],
        "promo_message": cur.get("promo_message", ""),
        "features": cur.get("features", {}),
        "limits": cur.get("limits", DEFAULT_LIMITS),
        "ai_settings": cur.get("ai_settings", {}),
        "featured_experiences": cur.get("featured_experiences", []),
    }
    # shallow merge
    for k, v in patch.items():
        if k == "limits" and isinstance(v, dict):
            body["limits"] = {**body["limits"], **v}
        else:
            body[k] = v
    r = requests.put(f"{BASE}/admin/config", json=body, headers={"Authorization": f"Bearer {tok}"}, timeout=30)
    jp("put /admin/config", r)
    r.raise_for_status()
    return r.json()


def signup_random():
    email = f"iter11_{uuid.uuid4().hex[:10]}@example.com"
    r = requests.post(f"{BASE}/auth/signup", json={"name": "Iter11", "email": email, "password": "Passw0rd!xyz"}, timeout=30)
    jp("signup", r)
    r.raise_for_status()
    j = r.json()
    return email, j.get("access_token") or j.get("token")


def generate(token=None, extra_headers=None, timeout=120):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if extra_headers:
        headers.update(extra_headers)
    return requests.post(f"{BASE}/sparks/generate", json=GEN_BODY, headers=headers, timeout=timeout)


def main():
    results = []
    admin_tok = admin_token()
    initial = get_config(admin_tok)
    print(f"Initial config: free_spark_limit={initial['free_spark_limit']} limits={initial.get('limits')}")

    # Ensure guest_ids_per_ip_daily is high enough in case shared IP state is near cap.
    # Not strictly needed since we don't use guest IDs below, but safer:
    try:
        put_config(admin_tok, {"limits": {"guest_ids_per_ip_daily": 200}})

        # PHASE 1: free_spark_limit=0
        put_config(admin_tok, {"free_spark_limit": 0})

        # (a) new signed-up user + X-Premium: 1 header → should be 402 (not 200/429)
        _, user_tok = signup_random()
        r_a = generate(token=user_tok, extra_headers={"X-Premium": "1"})
        jp("1a user+X-Premium", r_a)
        results.append(("1a user+X-Premium header", r_a.status_code == 402, r_a.status_code, r_a.text[:200]))

        # (b) same without header → 402
        r_b = generate(token=user_tok)
        jp("1b user no header", r_b)
        results.append(("1b user no header", r_b.status_code == 402, r_b.status_code, r_b.text[:200]))

        # (c) Admin (server-verified premium) with premium_daily_cap=0 → 429 with "resets automatically"
        put_config(admin_tok, {"limits": {"premium_daily_cap": 0}})
        r_c = generate(token=admin_tok)
        jp("1c admin premium_daily_cap=0", r_c)
        detail = ""
        try:
            detail = r_c.json().get("detail", "") or ""
        except Exception:
            pass
        results.append((
            "1c admin→429 w/'resets automatically'",
            r_c.status_code == 429 and "resets automatically" in detail,
            r_c.status_code,
            detail[:200],
        ))

        # restore premium_daily_cap and free quota
        put_config(admin_tok, {"limits": {"premium_daily_cap": 15}})
        put_config(admin_tok, {"free_spark_limit": 3})

    finally:
        # FINAL restore
        put_config(admin_tok, {"free_spark_limit": 3, "limits": DEFAULT_LIMITS})
        final = get_config(admin_tok)
        print(f"Final config: free_spark_limit={final['free_spark_limit']} limits={final.get('limits')}")
        assert final["free_spark_limit"] == 3, "free_spark_limit not restored"
        for k, v in DEFAULT_LIMITS.items():
            assert final["limits"].get(k) == v, f"limit {k} not restored (got {final['limits'].get(k)})"

    print("\n=== RESULTS ===")
    ok = True
    for name, passed, code, body in results:
        print(f"  {'PASS' if passed else 'FAIL'} :: {name} :: status={code} body={body}")
        if not passed:
            ok = False
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
