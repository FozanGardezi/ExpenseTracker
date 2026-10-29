"""Expense Tracker: bank and wallet transactions plus delivery orders, from your Gmail.

Run with:  streamlit run app.py

This file is the shell shared by every page:
1. Setup. Until the app is registered with Google, a setup page takes the
   Google client ID and secret (one time, by whoever runs the app).
2. Continue with Google. A signed-out visitor sees what the app will read,
   ticks that they allow it, and continues to one Google consent screen for
   their name, email and read-only Gmail. This file handles Google's redirect
   back from it, and remembers the browser for 30 days so a reload doesn't ask again.
3. Navigation: four tabs (Home, Activity, Accounts, Settings) with sub-tabs.
   The pages live in views/, their sub-tab sections in views/sections/.

Each user's data is kept apart in data/users/<id>/.
"""

import datetime as dt
from urllib.parse import urlparse

import streamlit as st
from google.auth.exceptions import GoogleAuthError, RefreshError

from order_tracker import auth
from order_tracker.config import (
    DEFAULT_REDIRECT_URI, GoogleConfig, load_google_config, save_google_config,
)
from order_tracker.parsers import PROVIDERS
from order_tracker.sync import available_sources
from order_tracker.users import User, save_profile, user_id_for
from views import dialogs
from views.common import (
    app_style, consent_markdown, current_user, flash, gmail_session, gmail_tokens, open_sessions, open_store,
    run_sync, session_cookie, set_session_cookie,
)
from views.components import follow_theme

st.set_page_config(page_title="Expense Tracker", page_icon="🧾", layout="wide")

AUTO_SYNC_AFTER = dt.timedelta(hours=6)
PRIVACY_PAGE = st.Page("views/privacy.py", title="Privacy", icon=":material/shield:")

config = load_google_config()
app_style()
follow_theme()

if "flash" in st.session_state:
    st.toast(st.session_state.pop("flash"))
if st.session_state.pop("clear_session_cookie", False):
    set_session_cookie("", days=0)  # just signed out


# --- one-time setup ---------------------------------------------------------------

def detected_redirect_uri() -> str:
    url = st.context.url
    if not url:
        return DEFAULT_REDIRECT_URI
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def setup() -> None:
    st.title("Set up Google access")
    st.write(
        "The app has to be registered with Google once before anyone can use it. Whoever runs "
        "the app does this. Users never see this page; they just continue with Google."
    )
    redirect = detected_redirect_uri()
    st.markdown(
        "1. In [Google Cloud Console](https://console.cloud.google.com/), create a project and "
        "enable the **Gmail API** (*APIs & Services → Library*).\n"
        "2. Set up the **OAuth consent screen**: user type *External*, and the scopes `openid`, "
        "`email`, `profile` and `https://www.googleapis.com/auth/gmail.readonly`. While testing, "
        "add each user's Gmail address under *Test users*.\n"
        "3. Under **Credentials**, create an **OAuth client ID** of type *Web application*, with "
        "this authorized redirect URI:"
    )
    st.code(redirect, language=None)
    st.markdown("4. Paste the client ID and secret here.")
    with st.form("google_client"):
        client_id = st.text_input("Client ID", placeholder="1234567890-abc.apps.googleusercontent.com")
        client_secret = st.text_input("Client secret", type="password")
        redirect_uri = st.text_input(
            "Redirect URI", value=redirect,
            help="Must match the authorized redirect URI in Google Cloud exactly.",
        )
        if st.form_submit_button("Save", type="primary"):
            if not client_id.strip().endswith(".apps.googleusercontent.com") or not client_secret.strip():
                st.warning("Enter the client ID (it ends in .apps.googleusercontent.com) and the client secret.")
            else:
                save_google_config(GoogleConfig(client_id.strip(), client_secret.strip(), redirect_uri.strip()))
                flash("Saved. The app is ready for users to continue with Google.")
                st.rerun()
    st.caption(
        "The client is stored encrypted in the data folder. This page is only shown until the "
        "app is set up; to change the client later, delete `data/google_client.enc`."
    )


if config is None:
    st.navigation([st.Page(setup, title="Setup", default=True), PRIVACY_PAGE], position="top").run()
    st.stop()


# --- Continue with Google ---------------------------------------------------------------

def complete_google_sign_in() -> None:
    """Handle Google's redirect back to the app (?code=...&state=... or ?error=...&state=...)."""
    params = st.query_params
    if "state" not in params:
        return
    code, state, error = params.get("code"), params["state"], params.get("error")
    st.query_params.clear()
    if not auth.verify_state(config.client_secret, state):
        st.error("That Google sign-in link has expired. Please continue with Google again.")
        return
    if error or not code:
        st.warning("You didn't continue with Google, so nothing was shared with the app.")
        return
    try:
        token = auth.exchange_code(config, code)
        claims = auth.identity(config, token)
    except (RuntimeError, ValueError, KeyError, GoogleAuthError) as exc:
        st.error(f"Google sign-in didn't complete: {exc}")
        return

    user = User(user_id_for(claims["sub"]), claims["email"], claims.get("name") or claims["email"])
    st.session_state["user"] = user
    st.session_state.pop("gmail", None)
    save_profile(user)
    # Remember this browser, so reloading the app doesn't ask again.
    sessions = open_sessions()
    st.session_state["session_token"] = sessions.create(user)
    sessions.close()

    if auth.GMAIL_SCOPE not in auth.granted_scopes(token):
        st.warning(
            "You're signed in, but Gmail access wasn't allowed (its box was left unticked on "
            "Google's screen), so the app won't read any email. You can allow it on **Gmail access**."
        )
        return
    tokens = gmail_tokens(user)
    if token.get("refresh_token"):
        tokens.save(token["refresh_token"], user.email)
    saved = tokens.load()
    creds = auth.build_credentials(
        config, saved["refresh_token"] if saved else None, token["access_token"], token.get("expires_in")
    )
    st.session_state["gmail"] = {"user_id": user.id, "creds": creds, "account": user.email}


def welcome() -> None:
    st.title("Expense Tracker")
    st.write(
        "Track your spending automatically from the emails your banks, wallets and delivery "
        "apps send you, instead of entering it by hand."
    )
    st.subheader("Before you continue")
    st.markdown(consent_markdown(
        [p.name for p in PROVIDERS.values()] + ["and the banks and wallets you choose"]
    ))
    agree = st.checkbox("I've read this and allow the app read-only access to my Gmail")
    st.link_button(
        "Continue with Google",
        auth.authorization_url(config, auth.make_state(config.client_secret)),
        type="primary",
        disabled=not agree,
    )
    st.caption(
        "Google will ask you to share your name, email address and read-only access to your "
        "Gmail. If you've allowed this before, it won't ask again, and this browser stays signed "
        "in for 30 days. Google opens in a new tab. See the **Privacy** page."
    )


def remembered_user() -> None:
    """Sign in a browser that continued with Google before and hasn't signed out."""
    if current_user() is not None:
        return
    token = session_cookie()
    sessions = open_sessions()
    user = sessions.lookup(token)
    sessions.close()
    if user:
        st.session_state["user"] = user
        st.session_state["session_token"] = token


complete_google_sign_in()
remembered_user()
if st.session_state.get("session_token") and st.session_state["session_token"] != session_cookie():
    set_session_cookie(st.session_state["session_token"])  # until the browser sends it back
user = current_user()
if user is None:
    st.navigation([st.Page(welcome, title="Welcome", default=True), PRIVACY_PAGE], position="top").run()
    st.stop()

store = open_store(user)
tokens = gmail_tokens(user)


# --- signed in ---------------------------------------------------------------------

def restore_gmail(user: User) -> None:
    if gmail_session(user):
        return
    saved = tokens.load()
    if not saved:
        return
    try:
        creds = auth.build_credentials(config, saved["refresh_token"])
    except RefreshError:
        tokens.delete()  # revoked at Google, or expired; the user has to allow access again
        return
    except GoogleAuthError as exc:
        st.warning(f"Could not reach Google to restore your Gmail connection: {exc}")
        return
    st.session_state["gmail"] = {"user_id": user.id, "creds": creds, "account": saved["account"]}


def should_auto_sync() -> bool:
    if not gmail_session(user) or st.session_state.get("auto_sync_done"):
        return False
    last = store.last_sync()
    return last is None or dt.datetime.now(dt.UTC) - last > AUTO_SYNC_AFTER


restore_gmail(user)
if should_auto_sync():
    run_sync(store, user, list(available_sources(store)), days=365)

# Four tabs; each groups related views as sub-tabs. Intro and controls are only on Home.
page = st.navigation(
    [
        st.Page("views/overview.py", title="Home", icon=":material/home:", default=True),
        st.Page("views/activity.py", title="Activity", icon=":material/receipt_long:"),
        st.Page("views/accounts.py", title="Accounts", icon=":material/account_balance:"),
        st.Page("views/settings.py", title="Settings", icon=":material/settings:"),
        # Kept at /privacy for signed-in users too; it's also a sub-tab of Settings.
        st.Page("views/privacy.py", title="Privacy", icon=":material/shield:", visibility="hidden"),
    ],
    position="top",
)
page.run()
dialogs.show_open_sheet()
