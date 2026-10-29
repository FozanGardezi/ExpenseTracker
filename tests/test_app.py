"""App tests: one-time setup, Continue with Google (and the Gmail permission in it),
per-user data, and every tab and sub-tab."""

import datetime as dt
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import plotly.io
import pytest
from streamlit.testing.v1 import AppTest

from order_tracker import auth, config
from order_tracker.budgets import Budget, Limit, month_key
from order_tracker.config import GoogleConfig
from order_tracker.institutions import PRESETS, statement_key
from order_tracker.models import Email, Order, StatementBatch, Transaction
from order_tracker.reconcile import reconcile
from order_tracker.rules import Rule
from order_tracker.storage import OrderStore
from order_tracker.users import User, load_profile, user_dir, user_id_for

APP = str(Path(__file__).resolve().parent.parent / "app.py")
# (page, sub-tab query parameter) for every screen of a signed-in user.
SCREENS = [
    ("views/overview.py", None),
    ("views/overview.py", ("home", "Trends")),
    ("views/overview.py", ("home", "Places")),
    ("views/overview.py", ("home", "Budget")),
    ("views/activity.py", ("activity", "Transactions")),
    ("views/activity.py", ("activity", "Statements")),
    ("views/activity.py", ("activity", "Transfers")),
    ("views/activity.py", ("activity", "Delivery orders")),
    ("views/accounts.py", ("accounts", "Banks & wallets")),
    ("views/accounts.py", ("accounts", "Statement settings")),
    ("views/accounts.py", ("accounts", "Import")),
    ("views/settings.py", ("settings", "Gmail & account")),
    ("views/settings.py", ("settings", "Categories")),
    ("views/settings.py", ("settings", "Skipped emails")),
    ("views/settings.py", ("settings", "Privacy")),
    ("views/privacy.py", None),
]
CONFIG = GoogleConfig("client-id.apps.googleusercontent.com", "client-secret", "http://localhost:8501")
ALICE = User(user_id_for("111"), "alice@gmail.com", "Alice")
BOB = User(user_id_for("222"), "bob@gmail.com", "Bob")
CLAIMS = {ALICE.id: {"sub": "111", "email": ALICE.email, "name": "Alice"},
          BOB.id: {"sub": "222", "email": BOB.email, "name": "Bob"}}


class FakeGmail:
    def __init__(self, creds):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A set-up app with nobody signed in, and no network."""
    monkeypatch.setenv("ORDER_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("order_tracker.config._secrets", lambda: {})  # never read real secrets
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GMAIL_TOKEN_KEY"):
        monkeypatch.delenv(name, raising=False)
    config.save_google_config(CONFIG)  # as if entered on the setup page
    monkeypatch.setattr("order_tracker.gmail_client.GmailClient", FakeGmail)
    monkeypatch.setattr("order_tracker.sync.sync_gmail", lambda *a, **k: {})
    revoked = []
    monkeypatch.setattr(auth, "revoke", lambda token: revoked.append(token) or True)
    monkeypatch.setattr(auth, "build_credentials", lambda *a, **k: object())
    browser = {"cookie": None}  # the remembered-sign-in cookie this test's browser sends
    monkeypatch.setattr("views.common.session_cookie", lambda: browser["cookie"])
    return {"revoked": revoked, "dir": tmp_path, "browser": browser}


def run_app(page: str | None = None, user: User | None = None, query: dict | None = None,
            tab: tuple[str, str] | None = None) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=30)
    if user:
        app.session_state["user"] = user  # what the Google callback leaves behind
    if query:
        app.query_params.update(query)
    app.run()
    if page:
        app.switch_page(page)
        app.run()
    if tab:
        app.query_params[tab[0]] = tab[1]  # a sub-tab, as a link to it would open
        app.run()
    assert not app.exception, app.exception
    return app


def connect(user: User) -> None:
    """A Gmail permission granted on an earlier visit."""
    from views.common import gmail_tokens

    gmail_tokens(user).save("refresh-" + user.id, user.email)


def saved_token(user: User) -> dict | None:
    from views.common import gmail_tokens

    return gmail_tokens(user).load()


def seed(user: User) -> None:
    store = OrderStore(user_dir(user.id) / "orders.db")
    store.save_institution(PRESETS[1])  # Meezan Bank
    now = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    store.add_order(Order("foodpanda", "foodpanda:A1", now, 1500.0, "PKR", "Homs", "Food"))
    store.add_order(Order("indrive", "indrive:msg:1", now, 600.0, "PKR", "inDrive City", "Ride"))
    store.add_transaction(Transaction("meezan", "meezan:R1", now, 1500.0, "PKR", "debit", "FOODPANDA", "Food"))
    store.add_transaction(Transaction("meezan", "meezan:R2", now, 3000.0, "PKR", "debit", "K-ELECTRIC", "Bills & utilities"))
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


def link_button(app: AppTest):
    return app.get("link_button")[0].proto


def url_params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def texts(app: AppTest) -> str:
    kinds = ("title", "header", "subheader", "markdown", "caption", "success", "warning", "error", "info")
    return " ".join(str(e.value) for kind in kinds for e in app.get(kind))


def button(app: AppTest, label: str):
    return next(b for b in app.button if b.label == label)


def html(app: AppTest) -> str:
    """The app's own HTML blocks (the hero figure, meters, a payment's sheet), as text."""
    return " ".join(e.proto.body for e in app.get("html"))


def tap_rows(app: AppTest, key: str) -> list[dict]:
    """The rows a tappable list (views/components.py) was given, by its key."""
    for element in app.get("bidi_component"):
        if element.proto.component_name == "tap_list" and element.proto.id.endswith(f"-{key}"):
            return json.loads(element.proto.json)["rows"]
    raise KeyError(key)


# --- one-time setup ---

def test_setup_page_until_the_google_client_is_saved(env):
    (env["dir"] / config.CLIENT_FILE).unlink()
    app = run_app()
    assert "Set up Google access" in texts(app)
    assert any(c.value == "http://localhost:8501" for c in app.code)  # redirect URI to register

    app.text_input[0].input(CONFIG.client_id)
    app.text_input[1].input(CONFIG.client_secret)
    button(app, "Save").click().run()
    assert config.load_google_config() == CONFIG
    assert "Before you continue" in texts(app)  # now on the welcome page


def test_setup_rejects_an_incomplete_client(env):
    (env["dir"] / config.CLIENT_FILE).unlink()
    app = run_app()
    app.text_input[0].input("not-a-client-id")
    button(app, "Save").click().run()
    assert config.load_google_config() is None
    assert "client secret" in texts(app)


# --- Continue with Google ---

def test_visitors_must_agree_before_continuing(env):
    app = run_app()
    assert "What the app will do" in texts(app)
    assert not app.sidebar.button  # nothing else until signed in
    assert link_button(app).disabled

    app.checkbox[0].check().run()
    params = url_params(link_button(app).url)
    assert not link_button(app).disabled
    assert auth.GMAIL_SCOPE in params["scope"].split() and "openid" in params["scope"].split()
    assert auth.verify_state(CONFIG.client_secret, params["state"])


def callback(env, monkeypatch, token: dict, who: User = ALICE, **query) -> AppTest:
    monkeypatch.setattr(auth, "exchange_code", lambda cfg, code: token)
    monkeypatch.setattr(auth, "identity", lambda cfg, tok: CLAIMS[who.id])
    params = {"code": "abc", "state": auth.make_state(CONFIG.client_secret), **query}
    return run_app(query={k: v for k, v in params.items() if v is not None})


GRANTED = {"access_token": "at", "refresh_token": "rt", "expires_in": 3600, "id_token": "jwt",
           "scope": f"openid email profile {auth.GMAIL_SCOPE}"}


def test_first_visit_signs_in_and_saves_the_gmail_permission(env, monkeypatch):
    app = callback(env, monkeypatch, GRANTED)
    assert app.session_state["user"] == ALICE
    assert saved_token(ALICE)["refresh_token"] == "rt"
    assert load_profile(user_dir(ALICE.id)) == ALICE
    assert app.title[0].value == "Hi, Alice"
    assert "Gmail connected" in texts(app)


def test_unticked_gmail_signs_in_without_gmail(env, monkeypatch):
    app = callback(env, monkeypatch, {**GRANTED, "scope": "openid email profile"})
    assert app.session_state["user"] == ALICE
    assert "Gmail access wasn't allowed" in texts(app)
    assert saved_token(ALICE) is None
    assert "Gmail not connected" in texts(app)


def test_returning_user_keeps_their_saved_permission(env, monkeypatch):
    connect(ALICE)
    app = callback(env, monkeypatch, {**GRANTED, "refresh_token": None})
    assert saved_token(ALICE)["refresh_token"] == "refresh-" + ALICE.id
    assert "Gmail connected" in texts(app)


def test_returning_user_without_a_saved_permission_is_asked_to_confirm(env, monkeypatch):
    app = callback(env, monkeypatch, {**GRANTED, "refresh_token": None})
    app.switch_page("views/settings.py")
    app.run()
    assert "for this visit only" in texts(app)
    confirm = url_params(link_button(app).url)
    assert confirm["prompt"] == "consent" and confirm["login_hint"] == ALICE.email


def test_cancelled_on_google(env):
    app = run_app(query={"error": "access_denied", "state": auth.make_state(CONFIG.client_secret)})
    assert "nothing was shared" in texts(app)
    assert "user" not in app.session_state


def test_expired_or_forged_link(env, monkeypatch):
    app = callback(env, monkeypatch, GRANTED, state="forged.1.abc")
    assert "expired" in texts(app)
    assert "user" not in app.session_state
    assert saved_token(ALICE) is None


def test_sign_out(env):
    connect(ALICE)
    app = run_app("views/settings.py", user=ALICE)
    button(app, "Sign out").click().run()
    assert "user" not in app.session_state
    assert "Before you continue" in texts(app)
    assert saved_token(ALICE) is not None  # signing out doesn't withdraw the permission


# --- Overview: intro and controls only here ---

def test_new_user_sees_the_setup_steps(env):
    app = run_app(user=ALICE)
    assert "Get started" in texts(app)
    steps = {link.proto.label: link.proto.disabled for link in app.get("page_link")}
    assert steps == {  # nothing done yet, so every step is open
        "Allow read-only Gmail access": False,
        "Add the banks and wallets you use": False,
        "Run your first sync with Sync now": False,
    }
    assert button(app, "Sync now").disabled


def test_finished_steps_are_greyed_out(env):
    connect(ALICE)
    app = run_app(user=ALICE)
    steps = {link.proto.label: link.proto.disabled for link in app.get("page_link")}
    assert steps["Allow read-only Gmail access"] is True
    assert steps["Add the banks and wallets you use"] is False


def test_setup_steps_disappear_once_done(env):
    seed(ALICE)
    connect(ALICE)
    app = run_app(user=ALICE)
    assert "Get started" not in texts(app)
    assert not button(app, "Sync now").disabled


def test_other_tabs_have_no_intro_or_controls(env):
    seed(ALICE)
    connect(ALICE)
    for page, tab in [s for s in SCREENS if s[0] not in ("views/overview.py", "views/privacy.py")]:
        app = run_app(page, user=ALICE, tab=tab)
        labels = {b.label for b in app.button}
        assert "Sync now" not in labels and "Get started" not in texts(app), (page, tab)


def test_reading_older_statements(env, monkeypatch):
    calls = []
    monkeypatch.setattr("order_tracker.sync.sync_gmail", lambda *a, **k: calls.append((a, k)) or {})
    seed(ALICE)
    connect(ALICE)
    app = run_app(user=ALICE)
    year = dt.date.today().year - 2
    app.selectbox(key="older_year").select(year).run()
    button(app, "Read these statements").click().run()
    assert not app.exception
    (args, kwargs), = [(a, k) for a, k in calls if k.get("since")]
    assert [s.key for s in args[2]] == [statement_key("meezan")]
    assert kwargs["since"] == dt.date(year, 1, 1)
    assert kwargs["until"] == dt.date(year + 1, 2, 14)  # 31 Dec + 45 days


def test_reading_older_statements_needs_gmail(env):
    seed(ALICE)
    app = run_app(user=ALICE)
    assert button(app, "Read these statements").disabled


# --- Gmail & account ---

def test_allowing_gmail_later(env):
    app = run_app("views/settings.py", user=ALICE)
    assert link_button(app).disabled
    app.checkbox(key="gmail_agree").check().run()
    params = url_params(link_button(app).url)
    assert params["prompt"] == "consent" and params["login_hint"] == ALICE.email


def test_disconnect_revokes_at_google(env):
    connect(ALICE)
    app = run_app("views/settings.py", user=ALICE)
    button(app, "Disconnect Gmail").click().run()
    assert env["revoked"] == ["refresh-" + ALICE.id]
    assert saved_token(ALICE) is None


def test_delete_my_data(env):
    seed(ALICE)
    connect(ALICE)
    app = run_app("views/settings.py", user=ALICE)
    assert button(app, "Delete my data").disabled
    app.checkbox(key="delete_confirm").check().run()
    button(app, "Delete my data").click().run()
    assert env["revoked"] == ["refresh-" + ALICE.id]
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    assert store.orders_frame().empty and store.transactions_frame().empty


# --- signed in ---

def test_privacy_page_is_public(env):
    app = run_app("views/privacy.py")
    assert "gmail.readonly" in texts(app)


def test_users_only_see_their_own_data(env):
    seed(ALICE)
    connect(ALICE)
    # 1,500 Foodpanda order paid by card + 600 cash inDrive + 3,000 bill + 1,200 from a statement;
    # the card debit isn't added again.
    assert '<div class="hero-value">Rs 6,300</div>' in html(run_app(user=ALICE))

    connect(BOB)
    bob = run_app(user=BOB)
    assert 'class="hero-value"' not in html(bob)
    assert "after the first sync" in texts(bob)


@pytest.mark.parametrize("page, tab", SCREENS)
def test_every_screen_runs_signed_in(env, page, tab):
    run_app(page, user=ALICE, tab=tab)


@pytest.mark.parametrize("page, tab", SCREENS)
def test_every_screen_runs_with_data_and_gmail(env, page, tab):
    seed(ALICE)
    connect(ALICE)
    run_app(page, user=ALICE, tab=tab)


def test_adding_a_preset_bank(env):
    app = run_app("views/accounts.py", user=ALICE)
    button(app, "Add").click().run()  # first preset is selected
    assert not app.exception
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    assert [i.key for i in store.institutions()] == [PRESETS[0].key]


# --- statements ---

def test_statements_show_spending_by_month_and_categories(env):
    seed(ALICE)
    app = run_app("views/activity.py", user=ALICE, tab=("activity", "Statements"))
    month = dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)
    headings = [h.value for h in app.subheader]
    assert headings[0] == "Spending each month"
    assert f"{month:%B} by category" in headings
    assert app.selectbox(key="stmt_month").value.month == month.month
    assert {m.label: m.value for m in app.metric}["Spent (PKR)"] == "1,200"
    table = next(d.value for d in app.dataframe if "category" in d.value.columns)  # the month's transactions
    assert table[["description", "category"]].values.tolist() == [["PSO STATION", "Fuel"]]


def test_statement_settings_list_read_and_unread_statements(env):
    seed(ALICE)
    app = run_app("views/accounts.py", user=ALICE, tab=("accounts", "Statement settings"))
    unread, read = (df.value for df in app.dataframe)
    assert "password-protected" in unread["reason"].item()
    assert read["bank"].tolist() == ["Meezan Bank"] and read["added"].tolist() == [1]


def test_saving_a_statement_password(env):
    seed(ALICE)
    app = run_app("views/accounts.py", user=ALICE, tab=("accounts", "Statement settings"))
    password = next(t for t in app.text_input if t.label == "Statement password")
    password.input("4321")
    button(app, "Save").click().run()
    assert not app.exception
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    assert store.institutions()[0].statement_password == "4321"
    assert store.processed_ids(statement_key("meezan")) == set()  # the locked one is retried


# --- staying signed in ---

def test_continuing_with_google_remembers_the_browser(env, monkeypatch):
    from views.common import open_sessions

    app = callback(env, monkeypatch, GRANTED)
    token = app.session_state["session_token"]
    assert open_sessions().lookup(token) == ALICE
    assert f"et_session={token}" in html(app)  # the cookie is set in the browser


def test_reload_with_the_cookie_skips_the_welcome(env):
    from views.common import open_sessions

    connect(ALICE)
    env["browser"]["cookie"] = open_sessions().create(ALICE)
    app = run_app()  # a fresh session, as after a reload
    assert app.title[0].value == "Hi, Alice"
    assert "Before you continue" not in texts(app)
    assert "Gmail connected" in texts(app)


def test_sign_out_forgets_the_browser(env):
    from views.common import open_sessions

    token = open_sessions().create(ALICE)
    env["browser"]["cookie"] = token
    app = run_app("views/settings.py")
    button(app, "Sign out").click().run()
    assert "Before you continue" in texts(app)
    assert "et_session=; Max-Age=0" in html(app)  # the cookie is cleared
    assert open_sessions().lookup(token) is None
    assert "Before you continue" in texts(run_app())  # and a reload no longer signs in


def test_unknown_cookie_shows_the_welcome(env):
    env["browser"]["cookie"] = "stale-or-forged"
    assert "Before you continue" in texts(run_app())


# --- transfers ---

def test_transfers_are_left_out_of_spending(env):
    seed(ALICE)
    connect(ALICE)
    app = run_app(user=ALICE)
    assert "Rs 6,300<" in html(app)  # not 26,300
    assert "Rs 20,000 sent by transfer isn't counted as spending." in texts(app)
    assert "Review transfers" in [link.proto.label for link in app.get("page_link")]


def test_setting_a_transfer_limit(env):
    seed(ALICE)
    app = run_app("views/activity.py", user=ALICE, tab=("activity", "Transfers"))
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Not counted (PKR)"] == "20.0K"
    app.number_input[0].set_value(25000)  # inside a form: submitted with Save
    button(app, "Save").click().run()
    assert not app.exception
    from order_tracker.ledger import transfer_rule
    assert transfer_rule(OrderStore(user_dir(ALICE.id) / "orders.db")) == (25000.0, "PKR")
    metrics = {m.label: m.value for m in run_app("views/activity.py", user=ALICE, tab=("activity", "Transfers")).metric}
    assert metrics["Counted as spending (PKR)"] == "20.0K"


# --- categories, rules and who spending was for ---

def test_monthly_spending_is_split_by_category(env):
    seed(ALICE)
    app = run_app(user=ALICE, query={"home": "Trends"})
    figure = plotly.io.from_json(app.get("plotly_chart")[0].proto.spec)
    bars = [(trace.name, sum(trace.y)) for trace in figure.data]
    # Biggest at the bottom; the transfer isn't spending.
    assert bars == [("Bills & utilities", 3000), ("Food", 1500), ("Fuel", 1200), ("Ride", 600)]
    assert [a.text for a in figure.layout.annotations] == ["6,300"]  # the month's total


def test_where_it_went_this_month(env):
    seed(ALICE)
    app = run_app(user=ALICE)
    donut = plotly.io.from_json(app.get("plotly_chart")[0].proto.spec).data[0]
    assert dict(zip(donut.labels, donut.values)) == {"Bills & utilities": 3000, "Food": 1500, "Fuel": 1200,
                                                      "Ride": 600}
    rows = tap_rows(app, "home_categories")
    assert [(r["title"], r["amount"], r["meta"]) for r in rows][0] == ("Bills & utilities", "Rs 3,000", "48%")
    latest = tap_rows(app, "home_recent")
    assert latest[0] == {"header": "Today"} or latest[0]["header"] == "Yesterday"
    assert {r.get("title") for r in latest} >= {"K-Electric", "Homs", "Ahmed Khan"}


def test_spending_for_home_and_mine(env):
    seed(ALICE)
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    store.save_rules([Rule(category_is="Bills & utilities", spent_for="Home")])
    store.close()
    app = run_app(user=ALICE)
    assert "Mine Rs 3,300 · Home Rs 3,000" in texts(app)
    app.segmented_control(key="home_for").set_value("Home").run()
    assert "You&#x27;ve spent for Home so far this month" in html(app) and "Rs 3,000<" in html(app)


def test_transactions_show_who_it_was_for_and_notes(env):
    seed(ALICE)
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    store.set_item_detail("txn:meezan:T1", "note", "Outing with Zain")
    store.set_item_detail("txn:meezan:T1", "counted", True)
    store.close()
    app = run_app("views/activity.py", user=ALICE, tab=("activity", "Transactions"))
    rows = {r["title"]: r for r in tap_rows(app, "txn_list") if "title" in r}
    assert rows["Ahmed Khan"]["sub"] == "Transfers · Meezan Bank · Outing with Zain"
    app.segmented_control(key="txn_view").set_value("Table").run()
    table = app.dataframe[0].value.set_index("description")
    assert table.loc["AHMED KHAN", ["spent_for", "note", "counted"]].tolist() == ["Mine", "Outing with Zain", True]
    assert "Rs 26,300<" in html(run_app(user=ALICE))  # now counted


def test_saving_your_lists(env):
    seed(ALICE)
    app = run_app("views/settings.py", user=ALICE, tab=("settings", "Categories"))
    app.text_input[0].set_value("Going out, Clothes")
    app.text_input[1].set_value("Me, Family")
    button(app, "Save lists").click().run()
    assert not app.exception
    from order_tracker.ledger import my_categories, spend_for_labels
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    assert (my_categories(store), spend_for_labels(store)) == (["Going out", "Clothes"], ["Me", "Family"])


def test_rules_show_how_many_transactions_they_match(env):
    seed(ALICE)
    store = OrderStore(user_dir(ALICE.id) / "orders.db")
    store.save_rules([Rule(["pso", "total"], category="Fuel"), Rule(category_is="Food", spent_for="Home")])
    store.close()
    app = run_app("views/settings.py", user=ALICE, tab=("settings", "Categories"))
    rules = next(d.value for d in app.dataframe if "matches" in d.value.columns)
    assert rules[["words", "matches"]].values.tolist() == [["pso, total", 1], ["", 1]]


# --- budgets, adding expenses, and what to keep an eye on ---

def store_of(user: User) -> OrderStore:
    return OrderStore(user_dir(user.id) / "orders.db")


def test_setting_a_budget_from_overview(env):
    seed(ALICE)
    app = run_app(user=ALICE)
    assert "Set how much you want to spend in a month" in texts(app)
    budget_input = next(n for n in app.number_input if n.label == "Monthly budget")
    budget_input.set_value(5000)
    button(app, "Set budget").click().run()
    assert not app.exception
    assert store_of(ALICE).budgets()[month_key(dt.date.today())] == Budget(5000, [])
    app = run_app(user=ALICE)
    # 6,300 of 5,000: over, with the reason spelled out.
    assert "You're **Rs 1,300** past your budget." in texts(app)
    assert "126% used" in html(app)


def test_limits_show_on_overview_and_in_the_budget_tab(env):
    seed(ALICE)
    store = store_of(ALICE)
    store.save_budget(month_key(dt.date.today()), Budget(100_000, [Limit("Eating out", 1000, "Food")]))
    store.close()
    app = run_app(user=ALICE)
    (limit,) = tap_rows(app, "home_limits")
    assert (limit["title"], limit["amount"], limit["sub"]) == ("Eating out", "Rs 1,500", "Rs 500 over")
    eye = tap_rows(app, "home_insights")
    assert eye[0]["title"] == "Eating out" and "Rs 500 over" in eye[0]["sub"]

    app = run_app(user=ALICE, query={"home": "Budget"})
    limits = next(d.value for d in app.dataframe if "words" in d.value.columns)
    assert limits[["name", "category", "amount", "spent"]].values.tolist() == [["Eating out", "Food", 1000, 1500]]


def test_adding_a_cash_expense(env):
    seed(ALICE)
    app = run_app(user=ALICE)
    button(app, "Add expense").click().run()
    next(n for n in app.number_input if n.label == "Amount").set_value(180)
    next(t for t in app.text_input if t.label == "What was it?").set_value("Samosas")
    next(t for t in app.text_input if t.label == "Note").set_value("With Zain")
    button(app, "Add").click().run()
    assert not app.exception
    rows = store_of(ALICE).transactions_frame()
    samosas = rows[rows["description"] == "Samosas"].iloc[0]
    assert (samosas["institution"], samosas["source"], samosas["amount"]) == ("cash", "manual", 180)
    app = run_app(user=ALICE)
    assert "Rs 6,480<" in html(app)
    latest = {r.get("title"): r for r in tap_rows(app, "home_recent")}
    assert latest["Samosas"]["sub"] == "Food · Cash · With Zain"


def test_pasting_a_bank_message(env):
    seed(ALICE)
    app = run_app(user=ALICE)
    button(app, "Add expense").click().run()
    app.segmented_control(key="add_how").set_value("Paste a bank message").run()
    app.text_area(key="add_text").input(
        "Meezan Bank: PKR 750.00 debited from A/c **1234 at DOUBLE SHOT on 05-Oct-2026 18:05. Avl Bal PKR 9,000"
    ).run()
    assert next(n for n in app.number_input if n.label == "Amount").value == 750
    assert next(t for t in app.text_input if t.label == "Paid to").value == "DOUBLE SHOT"
    button(app, "Add").click().run()
    assert not app.exception
    rows = store_of(ALICE).transactions_frame()
    shot = rows[rows["description"] == "DOUBLE SHOT"].iloc[0]
    assert (shot["institution"], shot["source"], shot["txn_date"].day) == ("meezan", "message", 5)


def test_a_coffee_habit_shows_up_to_keep_an_eye_on(env):
    seed(ALICE)
    store = store_of(ALICE)
    now = dt.datetime.now(dt.UTC)
    for i in range(10):
        store.add_transaction(Transaction("meezan", f"meezan:C{i}", now - dt.timedelta(minutes=i), 700.0, "PKR",
                                          "debit", "DOUBLE SHOT F-7", "Food"))
    store.close()
    app = run_app(user=ALICE)
    eye = {r["title"]: r for r in tap_rows(app, "home_insights")}
    assert eye["Double Shot F-7"]["sub"] == "10 times this month, Rs 7,000 in all (about Rs 700 each)."

    app = run_app(user=ALICE, query={"home": "Places"})
    app.text_input(key="places_search").input("double shot").run()
    assert "**Rs 7,000** this month" not in texts(app)  # the period is 3 months by default
    assert "10 times" in texts(app) and "Rs 7,000" in texts(app)
