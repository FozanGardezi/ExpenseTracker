"""Signed-in users and where each one's data lives.

Every user gets a directory of their own under data/users/, named from their
stable Google account id, holding their database and encrypted Gmail token.
Nothing is shared between users.
"""

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import data_dir


@dataclass(frozen=True)
class User:
    id: str
    email: str
    name: str


def user_id_for(subject: str) -> str:
    """Stable directory-safe id from Google's account id (the OIDC `sub` claim)."""
    return hashlib.sha256(f"google:{subject}".encode()).hexdigest()[:24]


def user_dir(user_id: str) -> Path:
    path = data_dir() / "users" / user_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def save_profile(user: User) -> None:
    """Record who a directory belongs to, so the command line can find users by email."""
    (user_dir(user.id) / "profile.json").write_text(json.dumps(asdict(user)))


def load_profile(directory: Path) -> User | None:
    try:
        return User(**json.loads((directory / "profile.json").read_text()))
    except (OSError, ValueError, TypeError):
        return None


def all_user_dirs() -> list[Path]:
    root = data_dir() / "users"
    return sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []


def delete_user_data(user_id: str) -> None:
    shutil.rmtree(data_dir() / "users" / user_id, ignore_errors=True)
