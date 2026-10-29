"""Remembering a signed-in browser, so reloading the app doesn't ask again.

After "Continue with Google", the browser keeps a random token in a cookie for
SESSION_DAYS. Only the token's SHA-256 hash is stored here, with the user it
belongs to and when it expires, so a copy of this database can't be used to
sign in. Signing out deletes the entry.
"""

import datetime as dt
import hashlib
import secrets
import sqlite3
from pathlib import Path

from .users import User

COOKIE = "et_session"
SESSION_DAYS = 30


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class SessionStore:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL, "
            "email TEXT NOT NULL, name TEXT NOT NULL, expires TEXT NOT NULL)"
        )
        self.conn.commit()

    def create(self, user: User) -> str:
        now = dt.datetime.now(dt.UTC)
        token = secrets.token_urlsafe(32)
        self.conn.execute("DELETE FROM sessions WHERE expires < ?", (now.isoformat(),))
        self.conn.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?, ?)",
            (_hash(token), user.id, user.email, user.name,
             (now + dt.timedelta(days=SESSION_DAYS)).isoformat()),
        )
        self.conn.commit()
        return token

    def lookup(self, token: str | None) -> User | None:
        if not token:
            return None
        row = self.conn.execute(
            "SELECT user_id, email, name FROM sessions WHERE token_hash = ? AND expires > ?",
            (_hash(token), dt.datetime.now(dt.UTC).isoformat()),
        ).fetchone()
        return User(*row) if row else None

    def delete(self, token: str | None) -> None:
        if token:
            self.conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_hash(token),))
            self.conn.commit()

    def close(self) -> None:
        self.conn.close()
