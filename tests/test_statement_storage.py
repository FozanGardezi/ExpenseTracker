"""Storing statements next to alerts without double counting, syncing statement
emails (now and for older periods), and upgrading existing databases."""

import datetime as dt
import sqlite3

import pytest

from order_tracker.institutions import StatementSource, source_key, statement_key
from order_tracker.ledger import build_ledger
from order_tracker.models import Attachment, Email, Institution, Order, StatementBatch, Transaction
from order_tracker.storage import OrderStore
from order_tracker.sync import available_sources, sync_gmail
from tests.statement_pdfs import bank_statement

MEEZAN = Institution("meezan", "Meezan Bank", "bank", ["meezan"])
NOON = dt.datetime(2026, 9, 2, 7, 0, tzinfo=dt.UTC)  # midday in Pakistan


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_TRACKER_DATA_DIR", str(tmp_path))
    monkeypatch.setattr("order_tracker.config._secrets", lambda: {})
    store = OrderStore(tmp_path / "orders.db")
    store.save_institution(MEEZAN)
    return store


def alert(key, amount, when, direction="debit"):
    return Transaction("meezan", key, when, amount, "PKR", direction, "FOODPANDA", "Food")


def row(key, amount, day, direction="debit"):
    when = dt.datetime(2026, 9, day, 7, 0, tzinfo=dt.UTC)
    return Transaction("meezan", f"meezan:stmt:s1:{key}", when, amount, "PKR", direction, "POS FOODPANDA",
                       "Food", source="statement")


def batch(*rows: Transaction) -> StatementBatch:
    return StatementBatch("meezan", "s1", dt.datetime(2026, 10, 2, tzinfo=dt.UTC), "e-Statement",
                          ["Sep.pdf"], dt.date(2026, 9, 1), dt.date(2026, 9, 30), list(rows))


def keys(store) -> list[str]:
    return sorted(store.transactions_frame()["txn_key"])


def test_statement_row_already_seen_as_an_alert_counts_once(store):
    store.add_transaction(alert("meezan:A1", 1884.99, dt.datetime(2026, 9, 1, 15, 16, tzinfo=dt.UTC)))
    assert store.add_statement(batch(row(0, 1884.99, 2), row(1, 3000.0, 4))) == 1
    assert keys(store) == ["meezan:A1", "meezan:stmt:s1:1"]
    linked = store.transactions_frame().set_index("txn_key").loc["meezan:A1", "statement_ref"]
    assert linked == "meezan:stmt:s1:0"

    # Reading the same statement again adds nothing.
    assert store.add_statement(batch(row(0, 1884.99, 2), row(1, 3000.0, 4))) == 0
    assert len(keys(store)) == 2


def test_alert_after_the_statement_replaces_the_statement_row(store):
    store.add_statement(batch(row(0, 1884.99, 2)))
    assert store.add_transaction(alert("meezan:A1", 1884.99, dt.datetime(2026, 9, 1, 15, 16, tzinfo=dt.UTC)))
    assert keys(store) == ["meezan:A1"]
    assert store.add_statement(batch(row(0, 1884.99, 2))) == 0  # still linked
    assert keys(store) == ["meezan:A1"]


def test_two_identical_payments_with_one_alert(store):
    store.add_transaction(alert("meezan:A1", 500.0, NOON))
    assert store.add_statement(batch(row(0, 500.0, 2), row(1, 500.0, 3))) == 1
    assert len(keys(store)) == 2
    spent = build_ledger(store)["amount"].sum()
    assert spent == 1000.0


def test_statement_rows_far_from_any_alert_are_kept(store):
    store.add_transaction(alert("meezan:A1", 500.0, NOON))
    store.add_statement(batch(row(0, 500.0, 20)))  # 18 days later: a different payment
    assert len(keys(store)) == 2


def test_statements_frame(store):
    store.add_statement(batch(row(0, 500.0, 2), row(1, 700.0, 3)))
    frame = store.statements_frame()
    assert frame.loc[0, ["institution", "rows_found", "rows_added", "files"]].tolist() == ["meezan", 2, 2, "Sep.pdf"]
    assert frame.loc[0, "period_end"] == dt.date(2026, 9, 30)


def test_one_email_can_be_read_by_alerts_and_statements(store):
    message = Email("m1", "Meezan", "Your e-Statement", NOON)
    store.mark_processed(message, source_key("meezan"), "skipped", "statement subject")
    assert store.processed_ids(statement_key("meezan")) == set()
    store.mark_processed(message, statement_key("meezan"), "added", "")
    assert store.processed_ids(source_key("meezan")) == {"m1"}
    assert store.processed_ids(statement_key("meezan")) == {"m1"}


def test_rescanning_a_bank_rereads_alerts_and_statements(store):
    store.add_transaction(alert("meezan:A1", 1884.99, NOON))
    store.add_statement(batch(row(0, 1884.99, 2), row(1, 3000.0, 4)))
    store.mark_processed(Email("s1", "x", "s", NOON), statement_key("meezan"), "added", "")
    store.forget_gmail_data([statement_key("meezan")])
    assert store.transactions_frame().empty
    assert store.statements_frame().empty
    assert store.processed_ids(statement_key("meezan")) == set()


def test_locked_statements_are_retried_after_a_password_is_saved(store):
    store.mark_processed(Email("s1", "x", "s", NOON), statement_key("meezan"), "skipped", "password-protected")
    store.mark_processed(Email("s2", "x", "s", NOON), statement_key("meezan"), "added", "")
    store.retry_unread_statements("meezan")
    assert store.processed_ids(statement_key("meezan")) == {"s2"}


def test_statement_password_is_encrypted_at_rest(store, tmp_path):
    store.save_institution(Institution("meezan", "Meezan Bank", "bank", ["meezan"], statement_password="4321"))
    assert store.institutions()[0].statement_password == "4321"
    raw = sqlite3.connect(tmp_path / "orders.db").execute("SELECT statement_password FROM institutions").fetchone()[0]
    assert raw and "4321" not in raw


def test_statement_sources_follow_the_bank_settings(store):
    assert statement_key("meezan") in available_sources(store)
    store.save_institution(Institution("meezan", "Meezan Bank", "bank", ["meezan"], statements=False))
    assert statement_key("meezan") not in available_sources(store)

    custom = Institution("meezan", "Meezan Bank", "bank", ["meezan"],
                         statement_senders=["estatement@meezanbank.com"], statement_subjects=["Account Summary"])
    assert StatementSource(custom).gmail_query == (
        'from:(estatement@meezanbank.com) subject:("Account Summary") has:attachment filename:pdf'
    )
    assert StatementSource(MEEZAN).gmail_query == (
        "from:(meezan) subject:(statement OR estatement) has:attachment filename:pdf"
    )


class FakeGmail:
    def __init__(self, emails: list[Email]):
        self.emails = {e.message_id: e for e in emails}
        self.queries: list[str] = []
        self.with_attachments: list[str] = []

    def list_message_ids(self, query: str) -> list[str]:
        self.queries.append(query)
        return list(self.emails) if "has:attachment" in query else []

    def get_email(self, message_id: str, attachments: bool = False) -> Email:
        if attachments:
            self.with_attachments.append(message_id)
        return self.emails[message_id]


def statement_email() -> Email:
    return Email("s1", "Meezan Bank", "Your e-Statement for September 2026",
                 dt.datetime(2026, 10, 2, 6, 0, tzinfo=dt.UTC), [],
                 [Attachment("Sep-2026.pdf", "application/pdf", bank_statement())])


def test_sync_reads_statement_pdfs(store):
    store.add_order(Order("foodpanda", "foodpanda:A1", dt.datetime(2026, 9, 2, 14, 0, tzinfo=dt.UTC),
                          1884.99, "PKR", "Homs", "Food"))
    gmail = FakeGmail([statement_email()])
    source = available_sources(store)[statement_key("meezan")]
    stats = sync_gmail(gmail, store, [source], days=365)[statement_key("meezan")]

    assert (stats.checked, stats.added) == (1, 5)
    assert gmail.with_attachments == ["s1"]
    ledger = build_ledger(store)
    # The statement's FOODPANDA debit is the foodpanda order, counted once.
    assert len(ledger) == 5
    assert ledger.loc[ledger["item"] == "order:foodpanda:A1", "paid_with"].item() == "Meezan Bank"
    assert store.last_sync() is not None


def test_reading_an_older_period(store):
    gmail = FakeGmail([statement_email()])
    source = available_sources(store)[statement_key("meezan")]
    sync_gmail(gmail, store, [source], since=dt.date(2023, 1, 1), until=dt.date(2024, 2, 15))
    start = int(dt.datetime(2023, 1, 1, tzinfo=dt.UTC).timestamp())
    end = int(dt.datetime(2024, 2, 15, tzinfo=dt.UTC).timestamp())
    assert gmail.queries[0].endswith(f"after:{start} before:{end}")
    assert store.last_sync() is None  # an older period isn't a regular sync


def test_existing_database_is_upgraded(tmp_path, monkeypatch):
    monkeypatch.setenv("ORDER_TRACKER_DATA_DIR", str(tmp_path))
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE institutions (key TEXT PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
            sender_terms TEXT NOT NULL, subject_terms TEXT NOT NULL DEFAULT '',
            currency TEXT NOT NULL DEFAULT 'PKR', enabled INTEGER NOT NULL DEFAULT 1);
        INSERT INTO institutions VALUES ('hbl', 'HBL', 'bank', 'hbl', '', 'PKR', 1);
        CREATE TABLE processed_messages (message_id TEXT PRIMARY KEY, provider TEXT NOT NULL,
            status TEXT NOT NULL, reason TEXT, subject TEXT, sender TEXT, received_at TEXT, account TEXT);
        INSERT INTO processed_messages VALUES ('m1', 'acct:hbl', 'added', '', 's', 'x', '2026-09-01T00:00:00+00:00', '');
        CREATE TABLE transactions (txn_key TEXT PRIMARY KEY, institution TEXT NOT NULL, txn_date TEXT NOT NULL,
            amount REAL NOT NULL, currency TEXT NOT NULL, direction TEXT NOT NULL, description TEXT,
            category TEXT, reference TEXT, account_hint TEXT, source TEXT NOT NULL, subject TEXT,
            message_id TEXT, account TEXT, matched_order TEXT, transfer_id TEXT);
    """)
    conn.close()

    store = OrderStore(path)
    hbl = store.institutions()[0]
    assert (hbl.key, hbl.statements, hbl.statement_password) == ("hbl", True, "")
    assert store.processed_ids("acct:hbl") == {"m1"}
    store.mark_processed(Email("m1", "x", "s", NOON), "stmt:hbl", "added", "")  # same email, second source
    assert store.processed_ids("stmt:hbl") == {"m1"}
    assert store.add_transaction(alert("hbl:A1", 100.0, NOON))


def test_statement_transactions_include_the_alerts_they_matched(store):
    store.add_transaction(alert("meezan:A1", 1884.99, dt.datetime(2026, 9, 1, 15, 16, tzinfo=dt.UTC)))
    store.add_transaction(alert("meezan:A2", 999.0, NOON))  # an alert no statement lists
    store.add_statement(batch(row(0, 1884.99, 2), row(1, 3000.0, 4)))
    listed = store.statement_transactions().set_index("txn_key")
    assert sorted(listed.index) == ["meezan:A1", "meezan:stmt:s1:1"]
    assert set(listed["statement_id"]) == {"s1"}
