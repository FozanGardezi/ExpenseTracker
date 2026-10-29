""""Continue with Google": signing in and granting read-only Gmail access in one step.

The app first explains what it reads and the user ticks that they allow it.
Then one Google consent screen asks for the user's name and email address
(OpenID) and read-only Gmail. Google lets the user untick Gmail on that
screen, so the granted scopes are checked before any Gmail access is kept.
Who the user is comes from the ID token Google returns, after verifying it.

The browser flow is done by hand rather than with google_auth_oauthlib's Flow,
because Streamlit starts a fresh session when Google redirects back. The
`state` parameter is an HMAC-signed (nonce, time) pair, so the callback can be
verified without server-side storage.
"""

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlencode

import google.oauth2.credentials
import requests
from cryptography.fernet import Fernet, InvalidToken
from google.auth.transport.requests import Request
from google.oauth2 import id_token

from .config import GoogleConfig

GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
SIGN_IN_SCOPES = ["openid", "email", "profile"]
SCOPES = [*SIGN_IN_SCOPES, GMAIL_SCOPE]
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
STATE_MAX_AGE_SECONDS = 600


def _sign(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


def make_state(secret: str) -> str:
    payload = f"{secrets.token_urlsafe(16)}.{int(time.time())}"
    return f"{payload}.{_sign(secret, payload)}"


def verify_state(secret: str, state: str) -> bool:
    try:
        nonce, issued, signature = state.split(".")
        age = time.time() - int(issued)
    except ValueError:
        return False
    expected = _sign(secret, f"{nonce}.{issued}")
    return hmac.compare_digest(signature, expected) and 0 <= age <= STATE_MAX_AGE_SECONDS


def authorization_url(
    config: GoogleConfig, state: str, *, confirm: bool = False, login_hint: str | None = None
) -> str:
    """Google's consent screen for name, email and read-only Gmail.

    Google shows the consent screen whenever something hasn't been granted yet;
    `confirm=True` shows it even when everything has, which is the only way to
    get a fresh long-lived token for a user whose saved one is gone.
    """
    params = {
        "client_id": config.client_id,
        "response_type": "code",
        "redirect_uri": config.redirect_uri,
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # a refresh token, so syncs work later and in the background
        "include_granted_scopes": "true",
        "prompt": "consent" if confirm else "select_account",
        "state": state,
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(config: GoogleConfig, code: str) -> dict:
    response = requests.post(
        TOKEN_URL,
        data={
            "client_id": config.client_id,
            "client_secret": config.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": config.redirect_uri,
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Google rejected the authorization code: {response.text}")
    return response.json()


def granted_scopes(token_response: dict) -> set[str]:
    return set(token_response.get("scope", "").split())


def identity(config: GoogleConfig, token_response: dict) -> dict:
    """The signed-in user's claims (sub, email, name) from Google's verified ID token."""
    claims = id_token.verify_oauth2_token(token_response["id_token"], Request(), config.client_id)
    if not claims.get("email"):
        raise ValueError("Google didn't share an email address")
    return claims


def build_credentials(
    config: GoogleConfig, refresh_token: str | None, access_token: str | None = None,
    expires_in: int | None = None,
) -> google.oauth2.credentials.Credentials:
    expiry = None
    if access_token and expires_in:
        # google-auth compares expiry against a naive UTC datetime.
        expiry = dt.datetime.now(dt.UTC).replace(tzinfo=None) + dt.timedelta(seconds=expires_in)
    creds = google.oauth2.credentials.Credentials(
        token=access_token,
        refresh_token=refresh_token,
        token_uri=TOKEN_URL,
        client_id=config.client_id,
        client_secret=config.client_secret,
        scopes=[GMAIL_SCOPE],  # Gmail calls need only this; refreshing asks for nothing more
        expiry=expiry,
    )
    if not creds.valid:
        creds.refresh(Request())
    return creds


def revoke(token: str) -> bool:
    """Withdraw the app's Gmail access at Google. Returns False if Google couldn't be reached."""
    try:
        response = requests.post(REVOKE_URL, data={"token": token}, timeout=15)
    except requests.RequestException:
        return False
    # 400 means the token was already invalid, which is just as revoked.
    return response.status_code in (200, 400)


class GmailTokenStore:
    """One user's Gmail refresh token, encrypted at rest."""

    def __init__(self, directory: Path, key: bytes):
        self.path = directory / "gmail_token.enc"
        self.fernet = Fernet(key)

    def save(self, refresh_token: str, account: str) -> None:
        payload = json.dumps({
            "refresh_token": refresh_token,
            "account": account,
            "granted_at": dt.datetime.now(dt.UTC).isoformat(),
        }).encode()
        fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(self.fernet.encrypt(payload))

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            saved = json.loads(self.fernet.decrypt(self.path.read_bytes()))
        except (OSError, InvalidToken, json.JSONDecodeError):
            return None
        return saved if saved.get("refresh_token") else None

    def delete(self) -> None:
        self.path.unlink(missing_ok=True)
