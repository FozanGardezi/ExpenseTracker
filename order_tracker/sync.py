"""Incremental Gmail sync: find each source's emails, parse the unseen ones, store
the orders, transactions and statements, then link payments to orders."""

import datetime as dt
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Protocol

from googleapiclient.errors import HttpError

from .gmail_client import GmailClient
from .institutions import InstitutionSource, StatementSource
from .models import Email, Order, StatementBatch, Transaction
from .parsers import PROVIDERS
from .reconcile import reconcile
from .storage import OrderStore

# (source name, emails done, emails to do)
ProgressCallback = Callable[[str, int, int], None]


class EmailSource(Protocol):
    """A delivery service, a bank's alerts or a bank's statements: emails that become records."""

    key: str
    name: str

    @property
    def gmail_query(self) -> str: ...

    def parse(self, email: Email) -> tuple[Order | Transaction | StatementBatch | None, str]: ...


@dataclass
class SyncStats:
    checked: int = 0
    added: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: int = 0


def available_sources(store: OrderStore) -> dict[str, EmailSource]:
    """Delivery services plus the user's enabled banks and wallets (alerts and
    statements), keyed by source key."""
    sources: dict[str, EmailSource] = dict(PROVIDERS)
    for institution in store.institutions():
        if institution.enabled:
            alerts = InstitutionSource(institution)
            sources[alerts.key] = alerts
            if institution.statements:
                statements = StatementSource(institution)
                sources[statements.key] = statements
    return sources


def _store(store: OrderStore, record, account: str) -> int:
    if isinstance(record, StatementBatch):
        return store.add_statement(record, account)
    if isinstance(record, Order):
        return int(store.add_order(record, account))
    return int(store.add_transaction(record, account))


def sync_gmail(
    client: GmailClient,
    store: OrderStore,
    sources: Iterable[EmailSource],
    days: int = 365,
    account: str = "",
    progress: ProgressCallback | None = None,
    *,
    since: dt.date | None = None,
    until: dt.date | None = None,
) -> dict[str, SyncStats]:
    """Read new emails from the last `days`, or from `since` to `until` for an
    older period. Only a regular sync (no `since`) counts as the last sync."""
    now = dt.datetime.now(dt.UTC)
    if since:
        after = int(dt.datetime.combine(since, dt.time(), tzinfo=dt.UTC).timestamp())
    else:
        after = int((now - dt.timedelta(days=days)).timestamp())
    window = f"after:{after}"
    if until:
        window += f" before:{int(dt.datetime.combine(until, dt.time(), tzinfo=dt.UTC).timestamp())}"
    results: dict[str, SyncStats] = {}

    for source in sources:
        stats = results[source.key] = SyncStats()
        processed = store.processed_ids(source.key)
        pending = [mid for mid in client.list_message_ids(f"{source.gmail_query} {window}")
                   if mid not in processed]

        for done, message_id in enumerate(pending, start=1):
            try:
                email = client.get_email(message_id, attachments=getattr(source, "needs_attachments", False))
            except HttpError:
                # Not marked as processed, so the next sync retries it.
                stats.errors += 1
                continue

            try:
                record, reason = source.parse(email)
            except Exception as exc:  # one odd email must not stop the sync
                record, reason = None, f"parser error: {exc}"

            if record is None:
                status = "skipped"
                stats.skipped += 1
            elif added := _store(store, record, account):
                status = "added"
                stats.added += added
            else:
                status, reason = "duplicate", "already recorded from another email or source"
                stats.duplicates += 1

            store.mark_processed(email, source.key, status, reason, account)
            stats.checked += 1
            if progress:
                progress(source.name, done, len(pending))

    reconcile(store)
    if not since:
        store.set_last_sync(now)
    return results
