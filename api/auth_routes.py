"""Continue with Google, for the phone app.

The app opens /auth/google/start in the system browser (never a web view, which
Google blocks). The server sends the user to Google's consent screen and handles
Google's redirect back at /auth/google/callback, using the same web OAuth client
and code as the Streamlit app. It then sends the browser back to the app with a
one-time code, and the app exchanges that code for a session token.

The code alone is useless: the app made up a random `verifier` before starting
and sent only its SHA-256 (`challenge`), and the exchange needs the verifier
itself. Another app that claims the same URL scheme and catches the redirect
can't sign in with it. This is PKCE (RFC 7636), between the app and this server.
"""

import base64
import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from dataclasses import replace
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from google.auth.exceptions import GoogleAuthError
from pydantic import BaseModel

from order_tracker import auth
from order_tracker.config import GoogleConfig, data_dir, load_google_config
from order_tracker.consent import consent_markdown
from order_tracker.parsers import PROVIDERS
from order_tracker.users import User, save_profile, user_id_for

from .common import bearer_token, current_user, gmail_tokens, open_sessions

router = APIRouter()

APP_SESSION_DAYS = 180  # the token sits in the phone's secure storage, not a shared browser
CODE_SECONDS = 300
STATE_SECONDS = 600
# Where the browser may be sent back to: the app's own scheme, Expo Go while developing, and
# the web build. A code is useless without the verifier, so this mainly stops the flow being
# used to bounce people to arbitrary sites.
DEFAULT_RETURN_PREFIXES = "expensetracker://,exp://,exps://,http://localhost:8081/"


def api_url() -> str:
    """Where this server is reached from outside, e.g. https://api.example.com."""
    return os.environ.get("API_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def google_config() -> GoogleConfig | None:
    """The app's Google client, with the redirect URI pointing at this server's callback."""
    config = load_google_config()
    return replace(config, redirect_uri=f"{api_url()}/auth/google/callback") if config else None


def return_allowed(url: str) -> bool:
    prefixes = os.environ.get("APP_RETURN_PREFIXES", DEFAULT_RETURN_PREFIXES)
    return any(url.startswith(p.strip()) for p in prefixes.split(",") if p.strip())


# --- signed state: what to come back to, carried through Google ---

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def make_state(secret: str, return_to: str, challenge: str) -> str:
    payload = _b64(json.dumps({"n": secrets.token_urlsafe(12), "t": int(time.time()),
                               "r": return_to, "c": challenge}).encode())
    return f"{payload}.{hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()}"


def read_state(secret: str, state: str) -> dict | None:
    try:
        payload, signature = state.rsplit(".", 1)
        expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_unb64(payload))
    except (ValueError, TypeError):
        return None
    return data if 0 <= time.time() - data.get("t", 0) <= STATE_SECONDS else None


# --- one-time codes, kept as hashes next to the sessions ---

def _codes() -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir() / "sessions.db")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS login_codes (code_hash TEXT PRIMARY KEY, challenge TEXT NOT NULL, "
        "user_id TEXT NOT NULL, email TEXT NOT NULL, name TEXT NOT NULL, expires REAL NOT NULL)"
    )
    return conn


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def issue_code(user: User, challenge: str) -> str:
    code = secrets.token_urlsafe(32)
    conn = _codes()
    with conn:
        conn.execute("DELETE FROM login_codes WHERE expires < ?", (time.time(),))
        conn.execute("INSERT INTO login_codes VALUES (?,?,?,?,?,?)",
                     (_hash(code), challenge, user.id, user.email, user.name, time.time() + CODE_SECONDS))
    conn.close()
    return code


def redeem_code(code: str, verifier: str) -> User | None:
    conn = _codes()
    with conn:
        row = conn.execute("SELECT challenge, user_id, email, name, expires FROM login_codes WHERE code_hash = ?",
                           (_hash(code),)).fetchone()
        conn.execute("DELETE FROM login_codes WHERE code_hash = ?", (_hash(code),))  # one try only
    conn.close()
    if row is None or row[4] < time.time():
        return None
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    return User(row[1], row[2], row[3]) if hmac.compare_digest(challenge, row[0]) else None


# --- the flow ---

def _back(return_to: str, **params: str) -> RedirectResponse:
    joiner = "&" if "?" in return_to else "?"
    return RedirectResponse(f"{return_to}{joiner}{urlencode(params)}", status_code=302)


def _page(title: str, text: str, status: int = 400) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><meta name=viewport content='width=device-width'><title>{title}</title>"
        f"<body style='font-family:system-ui;max-width:32rem;margin:3rem auto;padding:0 1rem'>"
        f"<h1>{title}</h1><p>{text}</p>", status_code=status)


@router.get("/auth/google/start")
def start(return_to: str, challenge: str, gmail: bool = False, login_hint: str | None = None):
    """Send the browser to Google's consent screen. `gmail` asks Google to show the screen
    even if everything was allowed before, which is how a lost Gmail permission is renewed."""
    config = google_config()
    if config is None:
        return _page("Not set up yet", "The app isn't registered with Google yet. See the README.", 503)
    if not return_allowed(return_to) or not 32 <= len(challenge) <= 128:
        return _page("Can't continue", "This sign-in link isn't valid. Go back to the app and try again.")
    state = make_state(config.client_secret, return_to, challenge)
    return RedirectResponse(auth.authorization_url(config, state, confirm=gmail, login_hint=login_hint),
                            status_code=302)


@router.get("/auth/google/callback")
def callback(state: str = "", code: str | None = None, error: str | None = None):
    config = google_config()
    data = read_state(config.client_secret, state) if config else None
    if data is None:
        return _page("That link has expired", "Go back to the app and continue with Google again.")
    return_to = data["r"]
    if error or not code:
        return _back(return_to, error="cancelled")
    try:
        token = auth.exchange_code(config, code)
        claims = auth.identity(config, token)
    except (RuntimeError, ValueError, KeyError, GoogleAuthError):
        return _back(return_to, error="google")

    user = User(user_id_for(claims["sub"]), claims["email"], claims.get("name") or claims["email"])
    save_profile(user)
    gmail = "not_allowed"
    if auth.GMAIL_SCOPE in auth.granted_scopes(token):
        tokens = gmail_tokens(user)
        if token.get("refresh_token"):
            tokens.save(token["refresh_token"], user.email)
        # Google only hands out a long-lived token on the consent screen; without one there's
        # nothing to sync with, and the app asks the user to confirm once more.
        gmail = "allowed" if tokens.load() else "confirm"
    return _back(return_to, code=issue_code(user, data["c"]), gmail=gmail)


class Exchange(BaseModel):
    code: str
    verifier: str


@router.post("/auth/exchange")
def exchange(body: Exchange) -> dict:
    """Swap the one-time code (and the verifier only the app knows) for a session token."""
    user = redeem_code(body.code, body.verifier)
    if user is None:
        raise HTTPException(400, "That sign-in has expired. Please continue with Google again.")
    sessions = open_sessions()
    token = sessions.create(user, days=APP_SESSION_DAYS)
    sessions.close()
    return {"token": token, "user": {"id": user.id, "email": user.email, "name": user.name},
            "expires": (dt.datetime.now(dt.UTC) + dt.timedelta(days=APP_SESSION_DAYS)).isoformat()}


@router.post("/auth/sign-out")
def sign_out(token: str | None = Depends(bearer_token), user: User = Depends(current_user)) -> dict:
    """Forget this phone's sign-in. Gmail access stays until it's disconnected."""
    sessions = open_sessions()
    sessions.delete(token)
    sessions.close()
    return {"message": "Signed out."}


@router.get("/api/config")
def public_config() -> dict:
    """What the sign-in screen needs before anyone is signed in."""
    return {
        "configured": google_config() is not None,
        "consent": consent_markdown([p.name for p in PROVIDERS.values()] + ["and the banks and wallets you choose"]),
        "privacy_url": f"{api_url()}/privacy",
    }
