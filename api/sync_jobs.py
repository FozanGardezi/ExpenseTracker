"""Syncing Gmail in the background, so the phone isn't kept waiting on one long request.

A sync is started with POST /api/sync and runs on a thread of its own; the app
polls GET /api/sync for its progress. Each user has at most one sync running.
Jobs live in this process's memory, so run the API as a single process (one
uvicorn worker), which is plenty: the work is waiting on Gmail.
"""

import datetime as dt
import threading
from dataclasses import asdict, dataclass, field

from google.auth.exceptions import GoogleAuthError, RefreshError
from googleapiclient.errors import HttpError

from order_tracker import auth, gmail_client, sync
from order_tracker.storage import OrderStore
from order_tracker.users import User, user_dir

from .auth_routes import google_config
from .common import gmail_tokens


@dataclass
class Job:
    running: bool = True
    source: str = ""          # what it's reading now
    done: int = 0             # emails read from that source
    total: int = 0            # emails to read from that source
    message: str = ""         # how it went, once finished
    error: str = ""           # why it stopped, if it did
    added: int = 0
    started_at: str = field(default_factory=lambda: dt.datetime.now(dt.UTC).isoformat())
    finished_at: str | None = None

    def public(self) -> dict:
        return asdict(self)


_jobs: dict[str, Job] = {}
_threads: dict[str, threading.Thread] = {}
_lock = threading.Lock()


def status(user_id: str) -> Job | None:
    return _jobs.get(user_id)


def running(user_id: str) -> bool:
    job = _jobs.get(user_id)
    return job is not None and job.running


def wait(user_id: str, timeout: float | None = None) -> None:
    """Block until the user's sync finishes (for tests and the command line)."""
    thread = _threads.get(user_id)
    if thread is not None:
        thread.join(timeout)


def start(user: User, source_keys: list[str] | None, days: int = 365, *, rescan: bool = False,
          since: dt.date | None = None, until: dt.date | None = None) -> bool:
    """Start a sync of `source_keys` (all the user's sources if None). False if one is already running."""
    with _lock:
        if running(user.id):
            return False
        job = _jobs[user.id] = Job()
        thread = threading.Thread(target=_run, args=(user, job, source_keys, days, rescan, since, until),
                                  name=f"sync-{user.id}", daemon=True)
        _threads[user.id] = thread
    thread.start()
    return True


def _run(user: User, job: Job, source_keys, days, rescan, since, until) -> None:
    store = OrderStore(user_dir(user.id) / "orders.db")
    try:
        _sync(user, job, store, source_keys, days, rescan, since, until)
    except Exception as exc:  # never leave a job "running" forever
        job.error = f"Sync stopped: {exc}"
    finally:
        store.close()
        job.running = False
        job.finished_at = dt.datetime.now(dt.UTC).isoformat()


def _sync(user, job, store, source_keys, days, rescan, since, until) -> None:
    config = google_config()
    tokens = gmail_tokens(user)
    saved = tokens.load()
    if config is None or saved is None:
        job.error = "Gmail isn't connected. Allow it under Settings → Gmail & account."
        return
    try:
        creds = auth.build_credentials(config, saved["refresh_token"])
    except RefreshError:
        tokens.delete()  # revoked at Google, or expired; the user has to allow access again
        job.error = "Gmail access was withdrawn. You can allow it again under Settings → Gmail & account."
        return
    except GoogleAuthError as exc:
        job.error = f"Couldn't reach Google: {exc}"
        return

    sources = sync.available_sources(store)
    keys = [k for k in (source_keys if source_keys is not None else list(sources)) if k in sources]
    if rescan:
        store.forget_gmail_data(keys)

    def progress(name: str, done: int, total: int) -> None:
        job.source, job.done, job.total = name, done, total

    job.source = "Searching Gmail"
    try:
        results = sync.sync_gmail(gmail_client.GmailClient(creds), store, [sources[k] for k in keys], days,
                                  saved["account"], progress, since=since, until=until)
    except RefreshError:
        tokens.delete()
        job.error = "Gmail access was withdrawn. You can allow it again under Settings → Gmail & account."
        return
    except (HttpError, GoogleAuthError) as exc:
        job.error = f"Sync stopped: {exc}"
        return

    job.added = sum(s.added for s in results.values())
    errors = sum(s.errors for s in results.values())
    job.message = f"Sync complete: {job.added} new {'entry' if job.added == 1 else 'entries'}."
    if errors:
        job.message += f" {errors} email(s) could not be downloaded and will be retried next time."
