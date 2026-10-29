"""Continue-with-Google security pieces, encrypted storage, and per-user data."""

import time
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet

from order_tracker import auth, config
from order_tracker.config import GoogleConfig
from order_tracker.users import User, all_user_dirs, delete_user_data, load_profile, save_profile, user_dir, user_id_for

CONFIG = GoogleConfig("client-id", "client-secret", "http://localhost:8501")


def test_state_is_signed():
    state = auth.make_state("secret")
    assert auth.verify_state("secret", state)
    assert not auth.verify_state("other-secret", state)
    assert not auth.verify_state("secret", state + "x")
    assert not auth.verify_state("secret", "garbage")


def test_state_expires(monkeypatch):
    state = auth.make_state("secret")
    issued = int(state.split(".")[1])
    monkeypatch.setattr(time, "time", lambda: issued + auth.STATE_MAX_AGE_SECONDS + 1)
    assert not auth.verify_state("secret", state)


def url_params(url: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_continue_with_google_asks_for_identity_and_read_only_gmail():
    params = url_params(auth.authorization_url(CONFIG, "the-state"))
    assert params["scope"].split() == [
        "openid", "email", "profile", "https://www.googleapis.com/auth/gmail.readonly",
    ]
    assert params["redirect_uri"] == CONFIG.redirect_uri
    assert params["access_type"] == "offline"
    assert params["prompt"] == "select_account"  # Google still shows consent for anything not yet granted
    assert params["state"] == "the-state"
    assert "login_hint" not in params


def test_confirming_again_forces_the_consent_screen():
    params = url_params(auth.authorization_url(CONFIG, "s", confirm=True, login_hint="me@gmail.com"))
    assert params["prompt"] == "consent"
    assert params["login_hint"] == "me@gmail.com"


def test_identity_comes_from_the_verified_id_token(monkeypatch):
    seen = {}

    def verify(token, request, audience):
        seen.update(token=token, audience=audience)
        return {"sub": "111", "email": "me@gmail.com", "name": "Me"}

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", verify)
    claims = auth.identity(CONFIG, {"id_token": "jwt"})
    assert claims["sub"] == "111"
    assert seen == {"token": "jwt", "audience": CONFIG.client_id}

    monkeypatch.setattr(auth.id_token, "verify_oauth2_token", lambda *a: {"sub": "111"})
    with pytest.raises(ValueError):
        auth.identity(CONFIG, {"id_token": "jwt"})


def test_granted_scopes():
    token = {"scope": "openid https://www.googleapis.com/auth/gmail.readonly"}
    assert auth.GMAIL_SCOPE in auth.granted_scopes(token)
    assert auth.GMAIL_SCOPE not in auth.granted_scopes({"scope": "openid email"})
    assert auth.granted_scopes({}) == set()


def test_token_store_encrypts_at_rest(tmp_path):
    key = Fernet.generate_key()
    store = auth.GmailTokenStore(tmp_path, key)
    store.save("refresh-123", "me@gmail.com")

    raw = store.path.read_bytes()
    assert b"refresh-123" not in raw and b"me@gmail.com" not in raw
    assert store.path.stat().st_mode & 0o777 == 0o600
    loaded = store.load()
    assert (loaded["refresh_token"], loaded["account"]) == ("refresh-123", "me@gmail.com")

    assert auth.GmailTokenStore(tmp_path, Fernet.generate_key()).load() is None  # wrong key
    store.delete()
    assert store.load() is None


def test_revoke(monkeypatch):
    calls = []

    class Response:
        def __init__(self, status):
            self.status_code = status

    monkeypatch.setattr(auth.requests, "post", lambda url, data, timeout: calls.append(data) or Response(200))
    assert auth.revoke("tok") and calls == [{"token": "tok"}]
    monkeypatch.setattr(auth.requests, "post", lambda *a, **k: Response(400))  # already invalid
    assert auth.revoke("tok")

    def unreachable(*a, **k):
        raise auth.requests.ConnectionError()

    monkeypatch.setattr(auth.requests, "post", unreachable)
    assert not auth.revoke("tok")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("order_tracker.config._secrets", lambda: {})
    for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GMAIL_TOKEN_KEY"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def test_google_client_from_setup_page_is_stored_encrypted(data_dir):
    assert config.load_google_config() is None
    config.save_google_config(CONFIG)
    assert config.load_google_config() == CONFIG
    raw = (data_dir / config.CLIENT_FILE).read_bytes()
    assert b"client-secret" not in raw


def test_environment_overrides_the_saved_client(data_dir, monkeypatch):
    config.save_google_config(CONFIG)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "env-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "env-secret")
    assert config.load_google_config().client_id == "env-id"


def test_user_ids_are_stable_and_distinct():
    assert user_id_for("1234") == user_id_for("1234")
    assert user_id_for("1234") != user_id_for("5678")


def test_users_get_separate_directories(data_dir):
    alice = User(user_id_for("1"), "alice@gmail.com", "Alice")
    bob = User(user_id_for("2"), "bob@gmail.com", "Bob")
    save_profile(alice)
    save_profile(bob)
    assert user_dir(alice.id) != user_dir(bob.id)
    assert {load_profile(d) for d in all_user_dirs()} == {alice, bob}

    delete_user_data(alice.id)
    assert [load_profile(d) for d in all_user_dirs()] == [bob]


# --- remembering a signed-in browser ---

def test_sessions_remember_a_browser_until_sign_out(tmp_path):
    from order_tracker.sessions import SessionStore

    store = SessionStore(tmp_path / "sessions.db")
    alice = User(user_id_for("1"), "alice@gmail.com", "Alice")
    token = store.create(alice)
    assert store.lookup(token) == alice
    assert store.lookup("not-a-token") is None and store.lookup(None) is None
    raw = (tmp_path / "sessions.db").read_bytes()
    assert token.encode() not in raw  # only the hash is kept
    store.delete(token)
    assert store.lookup(token) is None


def test_sessions_expire(tmp_path, monkeypatch):
    import datetime as dt

    from order_tracker import sessions

    store = sessions.SessionStore(tmp_path / "sessions.db")
    token = store.create(User(user_id_for("1"), "alice@gmail.com", "Alice"))
    later = dt.datetime.now(dt.UTC) + dt.timedelta(days=sessions.SESSION_DAYS + 1)

    class Later(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return later

    monkeypatch.setattr(sessions.dt, "datetime", Later)
    assert store.lookup(token) is None
