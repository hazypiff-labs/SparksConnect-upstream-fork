"""Browser E2E against the real web build + local backend (fake LLM, outbox mail)."""
import os, re, sys, time, uuid
from playwright.sync_api import sync_playwright, expect
from pymongo import MongoClient

APP = os.environ.get("E2E_APP_URL", "http://127.0.0.1:28502")
API = os.environ.get("E2E_API_URL", "http://127.0.0.1:28501")
DB = MongoClient(os.environ.get("E2E_MONGO_URL", "mongodb://127.0.0.1:27017"))[os.environ.get("E2E_DB_NAME", "sparks_e2e")]
SHOTS = os.environ.get("E2E_SCREENSHOT_DIR", ".")
email = f"e2e{uuid.uuid4().hex[:8]}@example.com"
results = []

def step(name, fn):
    try:
        fn(); results.append((name, "PASS"))
    except Exception as e:
        results.append((name, f"FAIL: {type(e).__name__}: {str(e)[:300]}"))
        page.screenshot(path=os.path.join(SHOTS, f"fail-{len(results)}.png"))
        raise

def code_for(kind):
    for _ in range(40):
        d = DB.email_outbox.find_one({"to": email, "kind": kind}, sort=[("created_at", -1)])
        if d: return re.search(r"code is (\d{6})", d["text"]).group(1)
        time.sleep(0.25)
    raise AssertionError(f"no {kind} mail")

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("E2E_CHROME") or None, headless=True)
    page = browser.new_page(viewport={"width": 420, "height": 900})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    T = page.get_by_test_id
    try:
        def welcome():
            page.goto(APP + "/")
            expect(T("welcome-screen")).to_be_visible(timeout=20000)
            expect(T("welcome-google-button")).to_have_count(0)  # no Google client ids in this build → hidden
        step("welcome renders; Google hidden without client ids", welcome)

        def signup():
            T("welcome-login-button").click()
            expect(T("auth-screen")).to_be_visible()
            T("auth-mode-signup").click()
            expect(T("legal-links")).to_contain_text("Terms of Use")
            T("auth-name-input").fill("Eve")
            T("auth-email-input").fill(email)
            T("auth-password-input").fill("Password123!")
            T("auth-submit-button").click()
            expect(T("verify-email-screen")).to_be_visible(timeout=15000)
        step("signup → verify-email screen", signup)

        def verify():
            T("verify-code").fill("000000" if code_for("verify_email") != "000000" else "111111")
            T("verify-submit").click()
            expect(T("verify-error")).to_be_visible()
            T("verify-code").fill(code_for("verify_email"))
            T("verify-submit").click()
            expect(T("verify-email-screen")).to_have_count(0, timeout=10000)
            assert DB.users.find_one({"email": email})["email_verified"] is True
        step("wrong code rejected, right code verifies", verify)

        def profile_logout():
            page.goto(APP + "/profile")
            expect(T("profile-name")).to_have_text("Eve", timeout=15000)
            expect(T("profile-verify-email")).to_have_count(0)
            expect(T("legal-links")).to_be_visible()
            T("profile-logout-button").click()
            expect(T("profile-login-button")).to_be_visible(timeout=10000)
        step("profile shows verified user; logout works", profile_logout)

        def reset():
            T("profile-login-button").click()
            T("auth-email-input").fill(email)
            T("auth-forgot").click()
            expect(T("forgot-screen")).to_be_visible()
            expect(T("forgot-email")).to_have_value(email)
            T("forgot-submit").click()
            expect(T("forgot-code")).to_be_visible(timeout=10000)
            T("forgot-code").fill(code_for("reset_password"))
            T("forgot-password").fill("BrandNew123!")
            T("forgot-submit").click()
            page.wait_for_url(re.compile(r"/home"), timeout=15000)
        step("forgot password → code → new password → signed in", reset)

        def login_new_password():
            page.goto(APP + "/profile")
            T("profile-logout-button").click()
            T("profile-login-button").click()
            T("auth-email-input").fill(email)
            T("auth-password-input").fill("Password123!")
            T("auth-submit-button").click()
            expect(T("auth-error")).to_contain_text("Incorrect", timeout=10000)
            T("auth-password-input").fill("BrandNew123!")
            T("auth-submit-button").click()
            expect(T("auth-screen")).to_have_count(0, timeout=10000)
        step("old password rejected, new password works", login_new_password)

        def paywall():
            page.goto(APP + "/premium")
            expect(T("premium-screen")).to_be_visible(timeout=15000)
            expect(T("legal-links")).to_contain_text("Privacy Policy")
            expect(T("premium-unavailable")).to_be_visible()  # web build: no store product → no invented price/trial
            expect(T("premium-price-card")).to_have_count(0)
            expect(page.get_by_text(re.compile("free trial for everyone"))).to_have_count(0)
        step("paywall never shows a price/trial the store didn't provide", paywall)

        def share_link():
            import requests
            g = {"X-Guest-ID": "g_" + uuid.uuid4().hex}
            sp = requests.post(f"{API}/api/sparks/generate", headers=g, json={"relationship_type": "partner", "vibes": ["romantic"], "budget": "under25", "distance": "10", "location": {"label": "X", "lat": 40.0, "lng": -74.0}}).json()["sparks"][0]
            page.goto(APP + f"/s/{sp['id']}")
            page.wait_for_url(re.compile(rf"/spark/{sp['id']}"), timeout=15000)
        step("/s/<id> app route redirects to the spark screen", share_link)

        def create_flow():
            page.goto(APP + "/create")
            T("who-option-partner").click(timeout=15000)
            T("who-continue-button").click()
            T("vibe-option-romantic").click()
            T("vibe-continue-button").click()
            T("budget-option-under25").click()
            T("budget-continue-button").click()
            T("distance-option-10").click()
            T("location-input").fill("Austin")
            T("location-search-button").click()
            expect(T("location-label")).to_contain_text("Austin", timeout=20000)  # geocode now needs an identity: the app sends one
            T("find-sparks-button").click()
            if T("when-find-sparks-button").count():
                T("when-find-sparks-button").click()
            expect(T("spark-card-0-title")).to_contain_text("Test Spark", timeout=30000)
            before = DB.sparks.count_documents({})
            T("different-ideas-button").click()
            page.wait_for_timeout(2500)
            assert DB.sparks.count_documents({}) == before + 3, "regenerate did not create a new batch"
            loc = DB.sparks.find_one(sort=[("created_at", -1)])["location"]
            assert set(loc) <= {"label", "lat", "lng"}, loc
        step("create wizard → geocode → results → different ideas", create_flow)
    finally:
        print("\n".join(f"{'✔' if r=='PASS' else '✘'} {n}: {r}" for n, r in results))
        print("page errors:", errors[:5])
        browser.close()
