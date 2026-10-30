"""API tests: Continue with Google from the phone app, sessions, keeping users apart,
syncing in the background, and every screen's endpoint."""

import base64
import datetime as dt
import hashlib
import io
import json
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from api import sync_jobs
from api.main import create_app
from order_tracker import auth, config
from order_tracker.budgets import Budget, Limit, month_key
from order_tracker.config import GoogleConfig
from order_tracker.institutions import PRESETS, statement_key
from order_tracker.models import Email, Order, StatementBatch, Transaction
from order_tracker.reconcile import reconcile
from order_tracker.sessions import SessionStore
from order_tracker.storage import OrderStore
from order_tracker.sync import SyncStats
from order_tracker.users import User, load_profile, user_dir, user_id_for

CONFIG = GoogleConfig("client-id.apps.googleusercontent.com", "client-secret", "http://localhost:8501")
ALICE = User(user_id_for("111"), "alice@gmail.com", "Alice Khan")
BOB = User(user_id_for("222"), "bob@gmail.com", "Bob")
CLAIMS = {"111": {"sub": "111", "email": ALICE.email, "name": ALICE.name},
          "222": {"sub": "222", "email": BOB.email, "name": BOB.name}}
GRANTED = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "id_token": "jwt",
           "scope": f"openid email profile {auth.GMAIL_SCOPE}"}
RETURN = "expensetracker://auth"
TZ = {"X-Timezone": "Asia/Karachi"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A set-up server with nobody signed in, and no network."""
    monkeypatch.setenv("ORDER_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("order_tracker.config._secrets", lambda: {})  # never read real secrets
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GMAIL_TOKEN_KEY", "API_PUBLIC_URL",
                 "APP_RETURN_PREFIXES", "APP_WEB_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    config.save_google_config(CONFIG)
    revoked = []
    monkeypatch.setattr(auth, "revoke", lambda token: revoked.append(token) or True)
    monkeypatch.setattr(auth, "build_credentials", lambda *a, **k: object())
    monkeypatch.setattr("order_tracker.gmail_client.GmailClient", lambda creds: object())
    synced = []

    def fake_sync(client, store, sources, days=365, account="", progress=None, *, since=None, until=None):
        synced.append({"sources": [s.key for s in sources], "days": days, "since": since, "until": until})
        if progress:
            progress("Foodpanda", 1, 1)
        store.set_last_sync(dt.datetime.now(dt.UTC)) if since is None else None
        return {"foodpanda": SyncStats(checked=3, added=2)}

    monkeypatch.setattr("order_tracker.sync.sync_gmail", fake_sync)
    return {"dir": tmp_path, "revoked": revoked, "synced": synced}


@pytest.fixture
def client(env):
    return TestClient(create_app())


def sign_in(user: User) -> dict:
    """Headers for a signed-in phone, as after Continue with Google."""
    sessions = SessionStore(config.data_dir() / "sessions.db")
    token = sessions.create(user, days=180)
    sessions.close()
    from order_tracker.users import save_profile

    save_profile(user)
    return {"Authorization": f"Bearer {token}", **TZ}


def connect(user: User) -> None:
    """A Gmail permission granted earlier."""
    auth.GmailTokenStore(user_dir(user.id), config.token_key()).save("refresh-" + user.id, user.email)


def saved_token(user: User) -> dict | None:
    return auth.GmailTokenStore(user_dir(user.id), config.token_key()).load()


def store_for(user: User) -> OrderStore:
    return OrderStore(user_dir(user.id) / "orders.db")


def seed(user: User) -> None:
    """A month with an order paid by card, a cash ride, a bill, a salary, a big transfer and a
    statement row; and a statement that couldn't be opened."""
    store = store_for(user)
    store.save_institution(PRESETS[1])  # Meezan Bank
    now = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    store.add_order(Order("foodpanda", "foodpanda:A1", now, 1500.0, "PKR", "Homs", "Food", subject="Your order"))
    store.add_order(Order("indrive", "indrive:msg:1", now, 600.0, "PKR", "inDrive City", "Ride"))
    store.add_transaction(Transaction("meezan", "meezan:R1", now, 1500.0, "PKR", "debit", "FOODPANDA", "Food"))
    store.add_transaction(Transaction("meezan", "meezan:R2", now, 3000.0, "PKR", "debit", "K-ELECTRIC",
                                      "Bills & utilities", reference="FT123"))
    store.add_transaction(Transaction("meezan", "meezan:R3", now, 50000.0, "PKR", "credit", "ACME LTD", "Income"))
    store.add_transaction(Transaction("meezan", "meezan:T1", now, 20000.0, "PKR", "debit", "AHMED KHAN", "Transfers"))
    statement_row = Transaction("meezan", "meezan:stmt:s1:0", now, 1200.0, "PKR", "debit", "PSO STATION",
                                "Fuel", source="statement")
    store.add_statement(StatementBatch("meezan", "s1", now, "e-Statement", ["Sep.pdf"],
                                       now.date().replace(day=1), now.date(), [statement_row]))
    store.mark_processed(Email("s2", "Meezan", "e-Statement August", now), statement_key("meezan"),
                         "skipped", "the PDF is password-protected: add the statement password")
    store.set_last_sync(dt.datetime.now(dt.UTC))
    reconcile(store)
    store.close()


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


VERIFIER = "v" * 64
CHALLENGE = b64(hashlib.sha256(VERIFIER.encode()).digest())


def params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def google_redirect(client, **extra) -> dict:
    response = client.get("/auth/google/start", params={"return_to": RETURN, "challenge": CHALLENGE, **extra},
                          follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith(auth.AUTH_URL)
    return params(response.headers["location"])


def come_back(client, monkeypatch, token: dict, sub: str = "111", **query) -> dict:
    """Google's redirect to the callback; returns what the app is sent back with."""
    monkeypatch.setattr(auth, "exchange_code", lambda cfg, code: token)
    monkeypatch.setattr(auth, "identity", lambda cfg, tok: CLAIMS[sub])
    state = query.pop("state", None) or google_redirect(client)["state"]
    response = client.get("/auth/google/callback", params={"code": "abc", "state": state, **query},
                          follow_redirects=False)
    assert response.status_code == 302, response.text
    assert response.headers["location"].startswith(RETURN + "?")
    return params(response.headers["location"])


# --- Continue with Google ---

def test_start_asks_google_for_name_email_and_read_only_gmail(client):
    sent = google_redirect(client)
    assert set(sent["scope"].split()) == {"openid", "email", "profile", auth.GMAIL_SCOPE}
    assert sent["redirect_uri"] == "http://localhost:8000/auth/google/callback"
    assert sent["access_type"] == "offline" and sent["prompt"] == "select_account"
    renew = google_redirect(client, gmail="true", login_hint=ALICE.email)
    assert renew["prompt"] == "consent" and renew["login_hint"] == ALICE.email


def test_start_only_returns_to_the_app(client, monkeypatch):
    bad = client.get("/auth/google/start", params={"return_to": "https://evil.example/x", "challenge": CHALLENGE},
                     follow_redirects=False)
    assert bad.status_code == 400
    short = client.get("/auth/google/start", params={"return_to": RETURN, "challenge": "abc"},
                       follow_redirects=False)
    assert short.status_code == 400
    monkeypatch.setenv("APP_RETURN_PREFIXES", "https://app.example.com/")
    ok = client.get("/auth/google/start", params={"return_to": "https://app.example.com/auth",
                                                  "challenge": CHALLENGE}, follow_redirects=False)
    assert ok.status_code == 302


def test_sign_in_end_to_end(client, monkeypatch):
    back = come_back(client, monkeypatch, GRANTED)
    assert back["gmail"] == "allowed"
    assert saved_token(ALICE)["refresh_token"] == "rt"
    assert load_profile(user_dir(ALICE.id)) == ALICE

    signed_in = client.post("/auth/exchange", json={"code": back["code"], "verifier": VERIFIER})
    assert signed_in.status_code == 200
    token = signed_in.json()["token"]
    assert signed_in.json()["user"]["email"] == ALICE.email
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["name"] == ALICE.name

    # The code works once.
    again = client.post("/auth/exchange", json={"code": back["code"], "verifier": VERIFIER})
    assert again.status_code == 400


def test_an_intercepted_code_is_useless_without_the_verifier(client, monkeypatch):
    back = come_back(client, monkeypatch, GRANTED)
    stolen = client.post("/auth/exchange", json={"code": back["code"], "verifier": "x" * 64})
    assert stolen.status_code == 400
    # A failed try uses the code up too.
    assert client.post("/auth/exchange", json={"code": back["code"], "verifier": VERIFIER}).status_code == 400


def test_unticked_gmail_signs_in_without_gmail(client, monkeypatch):
    back = come_back(client, monkeypatch, {**GRANTED, "scope": "openid email profile"})
    assert back["gmail"] == "not_allowed"
    assert saved_token(ALICE) is None
    assert client.post("/auth/exchange", json={"code": back["code"], "verifier": VERIFIER}).status_code == 200


def test_returning_user_keeps_their_permission_or_is_asked_to_confirm(client, monkeypatch):
    back = come_back(client, monkeypatch, {**GRANTED, "refresh_token": None})
    assert back["gmail"] == "confirm"  # nothing to sync with yet
    connect(ALICE)
    back = come_back(client, monkeypatch, {**GRANTED, "refresh_token": None})
    assert back["gmail"] == "allowed"
    assert saved_token(ALICE)["refresh_token"] == "refresh-" + ALICE.id


def test_cancelled_expired_and_forged(client, monkeypatch):
    state = google_redirect(client)["state"]
    cancelled = client.get("/auth/google/callback", params={"error": "access_denied", "state": state},
                           follow_redirects=False)
    assert params(cancelled.headers["location"]) == {"error": "cancelled"}
    forged = client.get("/auth/google/callback", params={"code": "abc", "state": "e30.abc"}, follow_redirects=False)
    assert forged.status_code == 400 and "expired" in forged.text
    monkeypatch.setattr("api.auth_routes.time.time", lambda: 10**10)  # long after the state was made
    late = client.get("/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert late.status_code == 400


def test_google_failure_is_reported_to_the_app(client, monkeypatch):
    def fail(cfg, code):
        raise RuntimeError("bad code")

    monkeypatch.setattr(auth, "exchange_code", fail)
    state = google_redirect(client)["state"]
    response = client.get("/auth/google/callback", params={"code": "abc", "state": state}, follow_redirects=False)
    assert params(response.headers["location"]) == {"error": "google"}


def test_not_set_up(client, env):
    (env["dir"] / config.CLIENT_FILE).unlink()
    assert client.get("/api/config").json()["configured"] is False
    response = client.get("/auth/google/start", params={"return_to": RETURN, "challenge": CHALLENGE},
                          follow_redirects=False)
    assert response.status_code == 503


def test_public_config_has_the_consent_text(client):
    body = client.get("/api/config").json()
    assert body["configured"] is True
    assert "What the app will do" in body["consent"] and "Foodpanda" in body["consent"]


# --- sessions and keeping users apart ---

def test_signed_out_requests_are_refused(client):
    assert client.get("/api/home/overview").status_code == 401
    assert client.get("/api/home/overview", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_sign_out_ends_only_this_phones_session(client):
    phone, tablet = sign_in(ALICE), sign_in(ALICE)
    connect(ALICE)
    assert client.post("/auth/sign-out", headers=phone).status_code == 200
    assert client.get("/api/me", headers=phone).status_code == 401
    assert client.get("/api/me", headers=tablet).status_code == 200
    assert saved_token(ALICE) is not None  # signing out doesn't withdraw Gmail


def test_users_only_see_their_own_data(client):
    seed(ALICE)
    alice, bob = sign_in(ALICE), sign_in(BOB)
    assert client.get("/api/home/overview", headers=alice).json()["empty"] is False
    assert client.get("/api/home/overview", headers=bob).json()["empty"] is True
    item = client.get("/api/activity/transactions", headers=alice).json()["rows"][0]["id"]
    assert client.get(f"/api/payments/{item}", headers=bob).status_code == 404
    assert client.patch(f"/api/payments/{item}", json={"note": "x"}, headers=bob).status_code == 404


# --- Home: status and syncing ---

def test_status_walks_through_the_setup_steps(client):
    headers = sign_in(ALICE)
    status = client.get("/api/home/status", headers=headers).json()
    assert status["first_name"] == "Alice"
    assert [s["done"] for s in status["steps"]] == [False, False, False]
    assert "Gmail not connected · not synced yet" == status["status"]
    connect(ALICE)
    seed(ALICE)
    status = client.get("/api/home/status", headers=headers).json()
    assert status["steps"] == [] and status["status"].startswith("Gmail connected · last synced")


def test_sync_needs_gmail(client, env):
    headers = sign_in(ALICE)
    assert client.post("/api/sync", json={}, headers=headers).status_code == 409
    assert client.post("/api/sync", json={"auto": True}, headers=headers).json()["started"] is False
    assert env["synced"] == []


def test_sync_runs_in_the_background_and_reports(client, env):
    headers = sign_in(ALICE)
    connect(ALICE)
    store = store_for(ALICE)
    store.save_institution(PRESETS[1])
    store.close()
    options = client.get("/api/sync/options", headers=headers).json()
    assert {"foodpanda", "acct:meezan", "stmt:meezan"} <= {s["key"] for s in options["sources"]}

    started = client.post("/api/sync", json={"sources": ["foodpanda", "acct:meezan"], "days": 90},
                          headers=headers).json()
    assert started["started"] is True
    sync_jobs.wait(ALICE.id, 10)
    job = client.get("/api/sync", headers=headers).json()["job"]
    assert job["running"] is False and job["message"] == "Sync complete: 2 new entries."
    assert env["synced"][-1] == {"sources": ["foodpanda", "acct:meezan"], "days": 90, "since": None, "until": None}

    # Just synced, so opening the app doesn't sync again.
    assert client.post("/api/sync", json={"auto": True}, headers=headers).json()["started"] is False


def test_sync_with_a_withdrawn_permission(client, monkeypatch):
    from google.auth.exceptions import RefreshError

    def refused(*a, **k):
        raise RefreshError("revoked")

    monkeypatch.setattr(auth, "build_credentials", refused)
    headers = sign_in(ALICE)
    connect(ALICE)
    client.post("/api/sync", json={}, headers=headers)
    sync_jobs.wait(ALICE.id, 10)
    assert "withdrawn" in client.get("/api/sync", headers=headers).json()["job"]["error"]
    assert saved_token(ALICE) is None


def test_read_older_statements(client, env):
    headers = sign_in(ALICE)
    connect(ALICE)
    store = store_for(ALICE)
    store.save_institution(PRESETS[1])
    store.close()
    response = client.post("/api/sync/older", json={"sources": ["stmt:meezan"], "year": 2023, "months": [2, 3]},
                           headers=headers).json()
    assert response["started"] and "01 Feb 2023 – 15 May 2023" in response["searching"]
    sync_jobs.wait(ALICE.id, 10)
    assert env["synced"][-1]["since"] == dt.date(2023, 2, 1)
    assert env["synced"][-1]["until"] == dt.date(2023, 5, 15)
    future = client.post("/api/sync/older", json={"sources": ["stmt:meezan"], "year": dt.date.today().year + 1},
                         headers=headers)
    assert future.status_code == 400


# --- Home: Overview and its sheets ---

def test_overview_of_this_month(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    body = client.get("/api/home/overview", headers=headers).json()
    assert body["empty"] is False and body["months"][0]["label"] == "This month"
    hero = body["hero"]
    assert hero["label"] == "You've spent so far this month" and hero["value"] == "Rs 6,300"
    assert "Rs 50,000 came in this month: income and refunds." in hero["notes"]
    assert hero["not_counted"] == "Rs 20,000 sent by transfer isn't counted as spending."
    assert body["budget"] == {"set": False, "title": f"{dt.date.today():%B} budget", "hint": None}
    where = body["where"]
    assert where["top"] == "Bills & utilities" and where["top_share"] == "48%"
    assert [c["category"] for c in where["categories"]] == ["Bills & utilities", "Food", "Fuel", "Ride"]
    assert {r["title"] for r in body["recent"]} >= {"Homs", "K-Electric", "Acme Ltd", "Pso Station"}
    assert "Ahmed Khan" in {r["title"] for r in body["recent"]}  # sent away, shown but not counted
    assert body["recent"][0]["day_label"] in ("Today", "Yesterday")


def test_overview_with_a_budget_and_limits(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    this_month = dt.date.today().replace(day=1)
    store = store_for(ALICE)
    store.save_budget(month_key(this_month), Budget(5000, [Limit("Bills", 2000, "Bills & utilities")]))
    store.close()
    body = client.get("/api/home/overview", headers=headers).json()
    assert body["budget"]["set"] is True and body["budget"]["status"] == "over"
    assert body["budget"]["sentence"].startswith("You're **Rs 1,300**")
    assert body["limits"][0] | {"share": None} == {
        "position": 0, "title": "Bills", "category": "Bills & utilities", "status": "over",
        "sub": "Rs 1,000 over", "amount": "Rs 3,000", "meta": "of Rs 2,000", "share": None}
    assert any(i["kind"] == "limit" and i["level"] == "critical" for i in body["insights"])


def test_overview_for_one_label(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    store = store_for(ALICE)
    store.set_item_detail("txn:meezan:R2", "spent_for", "Home")
    store.close()
    home = client.get("/api/home/overview", params={"spent_for": "Home"}, headers=headers).json()
    assert home["for"] == "Home" and home["hero"]["value"] == "Rs 3,000" and home["budget"] is None
    everyone = client.get("/api/home/overview", headers=headers).json()
    assert "Mine Rs 3,300 · Home Rs 3,000" in everyone["hero"]["notes"]


def test_drill_into_a_category_and_set_a_limit(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    sheet = client.get("/api/home/drill", params={"kind": "category", "key": "Fuel"}, headers=headers).json()
    assert sheet["title"] == "Fuel" and [r["title"] for r in sheet["rows"]] == ["Pso Station"]
    assert sheet["slots"] == client.get("/api/home/overview", headers=headers).json()["slots"]
    assert sheet["limit"] == {"name": "Fuel", "category": "Fuel", "words": []}
    saved = client.post("/api/home/budget/limits", json={**sheet["limit"], "amount": 10000}, headers=headers)
    assert saved.json()["message"] == "Fuel: a limit of Rs 10,000 a month. It shows on Home."
    limits = client.get("/api/home/overview", headers=headers).json()["limits"]
    assert limits[0]["title"] == "Fuel" and limits[0]["sub"] == "Rs 8,800 left"
    by_limit = client.get("/api/home/drill", params={"kind": "limit", "key": "0"}, headers=headers).json()
    assert by_limit["limit"] is None and "of Rs 10,000" in by_limit["subtitle"]
    assert client.get("/api/home/drill", params={"kind": "limit", "key": "5"}, headers=headers).status_code == 404


def test_drill_into_places_trends_and_searches(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    month = f"{dt.date.today():%Y-%m}"
    place = client.get("/api/home/drill", params={"kind": "place", "key": "homs"}, headers=headers).json()
    assert place["title"] == "Homs" and place["limit"]["words"] == ["homs"]
    trend = client.get("/api/home/drill", params={"kind": "trend", "key": f"{month}|Food"}, headers=headers).json()
    assert [r["title"] for r in trend["rows"]] == ["Homs"]
    whole = client.get("/api/home/drill", params={"kind": "trend", "key": month}, headers=headers).json()
    assert len(whole["rows"]) == 4
    found = client.get("/api/home/drill", params={"kind": "search", "key": "pso"}, headers=headers).json()
    assert found["title"] == "“pso”" and found["limit"]["words"] == ["pso"] and found["suggested"] == 1000
    places = client.get("/api/home/drill", params={"kind": "places", "key": "electric", "period": 3},
                        headers=headers).json()
    assert places["rows"][0]["title"] == "K-Electric" and places["suggested"] == 1000
    assert client.get("/api/home/drill", params={"kind": "nope"}, headers=headers).status_code == 400


def test_trends_and_places(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    trends = client.get("/api/home/trends", params={"range": "6"}, headers=headers).json()
    assert trends["range"] == "6" and trends["chart"][-1]["total"] == 6300.0
    assert {s["group"] for s in trends["chart"][-1]["segments"]} == {"Bills & utilities", "Food", "Fuel", "Ride"}
    assert trends["stats"][-1] == {"label": "This month so far", "value": "Rs 6,300", "help": None}
    assert {c["category"] for c in trends["categories"]} == {"Bills & utilities", "Food", "Fuel", "Ride"}
    assert trends["categories"][0]["change"] == "new"

    places = client.get("/api/home/places", params={"period": 1, "sort": "often", "search": "homs"},
                        headers=headers).json()
    assert {p["name"] for p in places["places"]} == {"Homs", "K-Electric", "Pso Station", "inDrive City"}
    assert places["found"]["empty"] is False and "**Rs 1,500**" in places["found"]["text"]
    assert client.get("/api/home/places", params={"search": "zzz"}, headers=headers).json()["found"]["empty"]


def test_budget_page(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    saved = client.put("/api/home/budget", json={"total": 80000, "limits": [
        {"name": "Coffee", "words": "double shot, gloria jeans", "amount": 3000},
        {"name": "Eating out", "category": "Food", "amount": 15000},
        {"name": "No amount", "category": "Food"},
        {},
    ]}, headers=headers).json()
    assert saved["saved"] == 2 and saved["skipped"] == 1
    budget = client.get("/api/home/budget", headers=headers).json()
    assert budget["total"] == 80000 and [lim["name"] for lim in budget["limits"]] == ["Coffee", "Eating out"]
    assert budget["limits"][1]["spent"] == "Rs 1,500"
    # Setting only the total keeps the limits.
    client.put("/api/home/budget", json={"total": 90000}, headers=headers)
    assert len(client.get("/api/home/budget", headers=headers).json()["limits"]) == 2


# --- payments and expenses ---

def test_change_a_payment(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    sheet = client.get("/api/payments/txn:meezan:R2", headers=headers).json()
    assert sheet["amount"] == "-Rs 3,000" and sheet["typed"] is None
    assert sheet["sentence"].startswith("Paid to **K-Electric** from **Meezan Bank** on ")
    assert {"label": "Reference", "value": "FT123"} in sheet["details"]

    client.patch("/api/payments/txn:meezan:R2", json={"category": "Rent", "spent_for": "Home", "note": "Flat",
                                                       "counted": False}, headers=headers)
    sheet = client.get("/api/payments/txn:meezan:R2", headers=headers).json()
    assert (sheet["category"], sheet["spent_for"], sheet["note"], sheet["counted"]) == ("Rent", "Home", "Flat", False)
    client.patch("/api/payments/txn:meezan:R2", json={"spent_for": None, "counted": True}, headers=headers)
    sheet = client.get("/api/payments/txn:meezan:R2", headers=headers).json()
    assert sheet["spent_for"] == "Mine" and sheet["counted"] is True  # back to what the rules say

    order = client.get("/api/payments/order:foodpanda:A1", headers=headers).json()
    assert order["sentence"].startswith("Foodpanda order from **Homs**, paid with **Meezan Bank**")
    assert client.patch("/api/payments/order:foodpanda:A1", json={"amount": 5}, headers=headers).status_code == 400
    assert client.delete("/api/payments/order:foodpanda:A1", headers=headers).status_code == 400
    assert client.get("/api/payments/txn:nope", headers=headers).status_code == 404


def test_add_change_and_remove_a_cash_expense(client):
    headers = sign_in(ALICE)
    options = client.get("/api/expenses/options", headers=headers).json()
    assert options["accounts"][0] == {"key": "cash", "name": "Cash"} and options["labels"] == ["Mine", "Home"]
    added = client.post("/api/expenses", json={"amount": 120, "description": "Samosas", "spent_for": "Home",
                                               "note": "Tea time"}, headers=headers)
    assert added.json()["message"] == "Added Samosas, Rs 120."
    item = added.json()["item"]
    sheet = client.get(f"/api/payments/{item}", headers=headers).json()
    assert sheet["category"] == "Food" and sheet["spent_for"] == "Home" and sheet["note"] == "Tea time"
    assert sheet["typed"]["account"] == "cash" and sheet["sentence"].startswith("**Samosas**, paid in cash")

    # Adding the same again asks first.
    twin = client.post("/api/expenses", json={"amount": 120, "description": "Samosas"}, headers=headers)
    assert twin.status_code == 409 and "already there" in twin.json()["detail"]["message"]
    forced = client.post("/api/expenses", json={"amount": 120, "description": "Samosas", "force": True},
                         headers=headers)
    assert forced.status_code == 200

    yesterday = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).date()
    client.patch(f"/api/payments/{item}", json={"amount": 150, "description": "Samosas and chai",
                                                 "date": yesterday.isoformat()}, headers=headers)
    sheet = client.get(f"/api/payments/{item}", headers=headers).json()
    assert sheet["amount"] == "-Rs 150" and sheet["typed"]["description"] == "Samosas and chai"
    tomorrow = dt.date.today() + dt.timedelta(days=2)
    assert client.patch(f"/api/payments/{item}", json={"date": tomorrow.isoformat()},
                        headers=headers).status_code == 400

    assert client.delete(f"/api/payments/{item}", headers=headers).json()["message"] == "Removed Samosas and chai."
    assert client.get(f"/api/payments/{item}", headers=headers).status_code == 404
    assert client.post("/api/expenses", json={"amount": 0, "description": ""}, headers=headers).status_code == 400


def test_paste_a_bank_message(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    text = "Meezan Bank: PKR 750 paid to DOUBLE SHOT from A/c **1234 on 05-Oct-2026 18:05"
    parsed = client.post("/api/expenses/parse", json={"text": text}, headers=headers).json()
    assert parsed["ok"] and parsed["account"] == "meezan"
    assert (parsed["direction"], parsed["amount"], parsed["date"]) == ("debit", 750.0, "2026-10-05")
    assert parsed["description"].lower().startswith("double shot")
    body = {"how": "message", "text": text, "account": "meezan", "amount": 750,
            "description": parsed["description"], "date": parsed["date"]}
    added = client.post("/api/expenses", json=body, headers=headers)
    assert added.status_code == 200
    sheet = client.get(f"/api/payments/{added.json()['item']}", headers=headers).json()
    assert {"label": "Came from", "value": "Pasted message"} in sheet["details"]
    again = client.post("/api/expenses", json={**body, "force": True}, headers=headers)
    assert again.status_code == 409 and again.json()["detail"]["message"] == "That message was already added."

    unreadable = client.post("/api/expenses/parse", json={"text": "Your OTP is 1234"}, headers=headers).json()
    assert unreadable["ok"] is False and "type it in" in unreadable["reason"]


# --- Activity ---

def test_transactions_list_filters_and_csv(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    everything = client.get("/api/activity/transactions", headers=headers).json()
    assert everything["total"] == 6 and everything["period"] == "Last 3 months"
    assert everything["slots"]["Bills & utilities"] == 0  # the same colors as on Overview
    assert "Meezan Bank" in everything["options"]["sources"]
    found = client.get("/api/activity/transactions", params={"search": "electric"}, headers=headers).json()
    assert [r["title"] for r in found["rows"]] == ["K-Electric"]
    food = client.get("/api/activity/transactions", params=[("categories", "Food"), ("categories", "Ride")],
                      headers=headers).json()
    assert {r["title"] for r in food["rows"]} == {"Homs", "inDrive City"}
    page = client.get("/api/activity/transactions", params={"offset": 2, "limit": 2}, headers=headers).json()
    assert len(page["rows"]) == 2 and page["total"] == 6
    old = client.get("/api/activity/transactions", params={"period": "Custom", "start": "2020-01-01",
                                                            "end": "2020-02-01"}, headers=headers).json()
    assert old["total"] == 0
    csv = client.get("/api/activity/transactions.csv", params={"search": "electric"}, headers=headers)
    assert csv.headers["content-type"].startswith("text/csv") and "K-ELECTRIC" in csv.text


def test_statements_transfers_and_orders(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    statements = client.get("/api/activity/statements", headers=headers).json()
    assert statements["empty"] is False and statements["rows"][0]["title"] == "Pso Station"
    assert statements["summary"][0] == {"label": "Spent", "value": "Rs 1,200"}
    assert statements["by_category"][0]["category"] == "Fuel"

    transfers = client.get("/api/activity/transfers", headers=headers).json()
    assert [r["title"] for r in transfers["rows"]] == ["Ahmed Khan"]
    assert transfers["summary"][2] == {"label": "Not counted", "value": "Rs 20,000"}
    saved = client.put("/api/activity/transfers/limit", json={"limit": 25000}, headers=headers).json()
    assert saved["message"] == "Transfers up to Rs 25,000 now count as spending."
    transfers = client.get("/api/activity/transfers", headers=headers).json()
    assert transfers["summary"][1] == {"label": "Counted as spending", "value": "Rs 20,000"}
    assert client.get("/api/home/overview", headers=headers).json()["hero"]["value"] == "Rs 26,300"

    orders = client.get("/api/activity/orders", headers=headers).json()
    assert {s["key"] for s in orders["services"]} == {"foodpanda", "indrive"}
    assert orders["summary"][0]["value"] == "Rs 2,100" and len(orders["orders"]) == 2
    one = client.get("/api/activity/orders", params={"services": "indrive", "search": "city"}, headers=headers).json()
    assert [o["title"] for o in one["orders"]] == ["inDrive City"]


def test_empty_screens(client):
    headers = sign_in(BOB)
    for path in ("/api/home/trends", "/api/home/places", "/api/activity/statements", "/api/activity/transfers",
                 "/api/activity/orders", "/api/activity/transactions"):
        body = client.get(path, headers=headers).json()
        assert body["empty"] is True, path
    assert client.get("/api/home/budget", headers=headers).json()["limits"] == []


# --- Accounts ---

def test_banks_and_wallets(client):
    headers = sign_in(ALICE)
    listing = client.get("/api/accounts/institutions", headers=headers).json()
    assert listing["tracked"] == [] and any(p["key"] == "meezan" for p in listing["presets"])
    assert client.post("/api/accounts/institutions", json={"preset": "meezan"}, headers=headers).status_code == 200
    assert client.post("/api/accounts/institutions", json={"preset": "meezan"}, headers=headers).status_code == 409
    custom = client.post("/api/accounts/institutions", json={
        "name": "Silkbank", "kind": "bank", "senders": "alerts@silkbank.com.pk, silkbank",
        "subjects": "Transaction Alert", "currency": "pkr"}, headers=headers).json()
    assert custom["key"] == "silkbank"
    assert client.post("/api/accounts/institutions", json={"name": "X"}, headers=headers).status_code == 400

    listing = client.get("/api/accounts/institutions", headers=headers).json()
    silk = next(i for i in listing["tracked"] if i["key"] == "silkbank")
    assert silk["alerts_query"] == 'from:(alerts@silkbank.com.pk OR silkbank) subject:("Transaction Alert")'
    assert silk["currency"] == "PKR"

    changed = client.patch("/api/accounts/institutions/silkbank", json={"enabled": False, "senders": "silk.com"},
                           headers=headers).json()
    assert "Re-scan" in changed["message"]
    silk = next(i for i in client.get("/api/accounts/institutions", headers=headers).json()["tracked"]
                if i["key"] == "silkbank")
    assert silk["enabled"] is False and silk["senders"] == "silk.com"
    assert client.delete("/api/accounts/institutions/silkbank", headers=headers).status_code == 200
    assert client.delete("/api/accounts/institutions/silkbank", headers=headers).status_code == 404


def test_statement_settings(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    page = client.get("/api/accounts/statements", headers=headers).json()
    assert page["unread"][0]["reason"].startswith("the PDF is password-protected")
    assert page["read"][0]["bank"] == "Meezan Bank" and page["read"][0]["found"] == 1
    assert page["settings"][0]["has_password"] is False
    saved = client.put("/api/accounts/institutions/meezan/statements", json={
        "statements": True, "password": "4210112345671", "senders": "estatement@meezanbank.com"}, headers=headers)
    assert "tried again" in saved.json()["message"]
    page = client.get("/api/accounts/statements", headers=headers).json()
    assert page["settings"][0]["has_password"] is True and page["unread"] == []  # retried on the next sync
    store = store_for(ALICE)
    assert store.institutions()[0].statement_password == "4210112345671"
    store.close()
    client.put("/api/accounts/institutions/meezan/statements", json={"statements": False, "remove_password": True},
               headers=headers)
    assert client.get("/api/accounts/statements", headers=headers).json()["settings"][0]["has_password"] is False


def test_import_a_csv_file(client):
    headers = sign_in(ALICE)
    data = b"Booking ID,Pickup Time,Car Type,Total Fare\nB-1,03/10/2026 10:15,Go,PKR 450\nB-2,bad,Go,\n"
    files = {"file": ("careem_rides.csv", io.BytesIO(data), "text/csv")}
    preview = client.post("/api/accounts/import/csv/preview", files=files, headers=headers).json()
    assert preview["service"] == "careem"
    assert preview["mapping"] == {"date": "Pickup Time", "amount": "Total Fare", "merchant": "Car Type",
                                  "reference": "Booking ID", "currency": None}
    form = {"service": "careem", "mapping": json.dumps(preview["mapping"]), "currency": "PKR", "dayfirst": "true"}
    dry = client.post("/api/accounts/import/csv", data={**form, "dry_run": "true"},
                      files={"file": ("careem_rides.csv", io.BytesIO(data), "text/csv")}, headers=headers).json()
    assert dry["ready"] == 1 and dry["bad_rows"] == 1
    done = client.post("/api/accounts/import/csv", data=form,
                       files={"file": ("careem_rides.csv", io.BytesIO(data), "text/csv")}, headers=headers).json()
    assert done["added"] == 1
    again = client.post("/api/accounts/import/csv", data=form,
                        files={"file": ("careem_rides.csv", io.BytesIO(data), "text/csv")}, headers=headers).json()
    assert again["message"] == "Imported 0 new order(s); 1 were already there."
    no_date = client.post("/api/accounts/import/csv", data={**form, "mapping": json.dumps({"amount": "Total Fare"})},
                          files={"file": ("x.csv", io.BytesIO(data), "text/csv")}, headers=headers)
    assert no_date.status_code == 400


def test_import_foodpanda_history(client, monkeypatch):
    from order_tracker.foodpanda_account import FoodpandaAuthError

    items = [{"order_code": "x1", "total_value": 990, "ordered_at": {"date": "2026-09-01 20:00:00"},
              "vendor": {"name": "Homs"}}, {"order_code": "x2", "decline_reason": "closed"}]
    monkeypatch.setattr("api.accounts.fetch_order_history", lambda token, country: items)
    headers = sign_in(ALICE)
    done = client.post("/api/accounts/import/foodpanda", json={"token": "Bearer abc"}, headers=headers).json()
    assert done["message"] == "Found 2 orders: 1 new, 0 already tracked, 1 declined or unreadable."

    def refused(token, country):
        raise FoodpandaAuthError("foodpanda refused the token")

    monkeypatch.setattr("api.accounts.fetch_order_history", refused)
    failed = client.post("/api/accounts/import/foodpanda", json={"token": "abc"}, headers=headers)
    assert failed.status_code == 502 and "refused" in failed.json()["detail"]


# --- Settings ---

def test_account_gmail_and_deleting_data(client, env):
    seed(ALICE)
    headers = sign_in(ALICE)
    page = client.get("/api/settings/account", headers=headers).json()
    assert page["gmail"]["connected"] is False and "Meezan Bank" in page["reads_from"]
    connect(ALICE)
    page = client.get("/api/settings/account", headers=headers).json()
    assert page["gmail"] == {"connected": True, "account": ALICE.email, "since": f"{dt.date.today():%d %b %Y}"}
    assert any(q["query"].startswith("from:(meezanbank OR meezan)") for q in page["queries"])

    assert "withdrawn at Google" in client.delete("/api/settings/gmail", headers=headers).json()["message"]
    assert env["revoked"] == ["refresh-" + ALICE.id] and saved_token(ALICE) is None

    connect(ALICE)
    assert client.delete("/api/settings/data", headers=headers).status_code == 200
    assert env["revoked"][-1] == "refresh-" + ALICE.id
    assert client.get("/api/home/overview", headers=headers).json()["empty"] is True  # still signed in


def test_rules_and_lists(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    saved = client.put("/api/settings/rules", json={"rules": [
        {"words": "k-electric, lesco", "spent_for": "Home"},
        {"words": "pso", "min_amount": 1000, "category": "Car"},
        {"words": "nothing to set"},
        {},
    ]}, headers=headers).json()
    assert saved["message"] == "Saved 2 rules. 1 left out: a rule needs something to look for and a category or For to set."
    rules = client.get("/api/settings/rules", headers=headers).json()
    assert [r["matches"] for r in rules["rules"]] == [1, 1]
    assert client.get("/api/payments/txn:meezan:stmt:s1:0", headers=headers).json()["category"] == "Car"

    client.put("/api/settings/lists", json={"categories": "Going out, Car", "spend_for": ["Me", "Family"]},
               headers=headers)
    rules = client.get("/api/settings/rules", headers=headers).json()
    assert rules["my_categories"] == ["Going out", "Car"] and rules["labels"] == ["Me", "Family"]
    assert "Going out" in rules["categories"]


def test_skipped_emails_and_privacy(client):
    seed(ALICE)
    headers = sign_in(ALICE)
    skipped = client.get("/api/settings/skipped", headers=headers).json()
    assert skipped["sources"] == ["Meezan Bank statements"] and skipped["rows"][0]["subject"] == "e-Statement August"
    assert client.get("/api/settings/skipped", params={"sources": "Foodpanda"}, headers=headers).json()["rows"] == []

    assert "read-only" in client.get("/api/privacy").json()["markdown"]
    page = client.get("/privacy")
    assert page.status_code == 200 and "<h1>Privacy</h1>" in page.text
    assert '<a href="https://myaccount.google.com/permissions">' in page.text
    assert "<code>gmail.readonly</code>" in page.text


def test_web_build_origin_is_allowed(client):
    preflight = client.options("/api/home/overview", headers={
        "Origin": "http://localhost:8081", "Access-Control-Request-Method": "GET",
        "Access-Control-Request-Headers": "authorization,x-timezone"})
    assert preflight.headers["access-control-allow-origin"] == "http://localhost:8081"
    other = client.options("/api/home/overview", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in other.headers
