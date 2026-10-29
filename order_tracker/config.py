"""Configuration: the app's Google OAuth client, data directory and encryption key.

The Google client (ID and secret) is the app's registration with Google; every
user then grants their own permission in the app. It can come from, in order:
environment variables, .streamlit/secrets.toml ([google]), or the app's own
one-time setup page, which stores it encrypted in the data directory.
"""

import json
import os
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SECRETS_FILE = PROJECT_ROOT / ".streamlit" / "secrets.toml"
DEFAULT_REDIRECT_URI = "http://localhost:8501"
CLIENT_FILE = "google_client.enc"


@dataclass(frozen=True)
class GoogleConfig:
    client_id: str
    client_secret: str
    redirect_uri: str  # where Google returns after "Continue with Google"


def data_dir() -> Path:
    """Directory holding each user's database and Gmail token."""
    path = Path(os.environ.get("ORDER_TRACKER_DATA_DIR", PROJECT_ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _secrets() -> dict:
    """st.secrets inside the app (covers hosted platforms), the secrets file from the command line."""
    from streamlit import runtime

    if runtime.exists():
        import streamlit as st

        try:
            return st.secrets.to_dict()
        except (FileNotFoundError, KeyError):
            return {}
    if not SECRETS_FILE.exists():
        return {}
    with SECRETS_FILE.open("rb") as fh:
        return tomllib.load(fh)


def load_google_config() -> GoogleConfig | None:
    """The app's Google OAuth client, or None until it has been set up."""
    google = _secrets().get("google", {})
    client_id = os.environ.get("GOOGLE_CLIENT_ID") or google.get("client_id")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET") or google.get("client_secret")
    if client_id and client_secret:
        redirect_uri = (
            os.environ.get("GOOGLE_REDIRECT_URI") or google.get("redirect_uri") or DEFAULT_REDIRECT_URI
        )
        return GoogleConfig(client_id, client_secret, redirect_uri)
    return _load_saved_client()


def save_google_config(config: GoogleConfig) -> None:
    """Store the client entered on the setup page, encrypted."""
    from cryptography.fernet import Fernet

    data = Fernet(token_key()).encrypt(json.dumps(asdict(config)).encode())
    path = data_dir() / CLIENT_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)


def _load_saved_client() -> GoogleConfig | None:
    from cryptography.fernet import Fernet, InvalidToken

    path = data_dir() / CLIENT_FILE
    if not path.exists():
        return None
    try:
        return GoogleConfig(**json.loads(Fernet(token_key()).decrypt(path.read_bytes())))
    except (OSError, InvalidToken, ValueError, TypeError):
        return None


def contact_email() -> str | None:
    """Who users can contact about their data ([app] contact_email), shown on the Privacy page."""
    return _secrets().get("app", {}).get("contact_email")


def token_key() -> bytes:
    """Key that encrypts stored Gmail tokens and the saved Google client.

    Set [gmail] token_key (or GMAIL_TOKEN_KEY) for any shared deployment. For a
    local install, a key is generated once and kept in the data directory.
    """
    configured = os.environ.get("GMAIL_TOKEN_KEY") or _secrets().get("gmail", {}).get("token_key")
    if configured:
        return configured.encode()
    from cryptography.fernet import Fernet

    path = data_dir() / ".token_key"
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(Fernet.generate_key())
    return path.read_bytes().strip()
