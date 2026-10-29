"""SQLite storage for orders, bank/wallet transactions (from emails, or added by
the user), monthly statements, the tracked banks and wallets, category edits,
rules and budgets, and which Gmail messages have been processed.

Keeping processed message ids means each sync only downloads emails it has not
seen before, so frequent automatic syncs stay cheap.
"""

import datetime as dt
import sqlite3
import uuid
from pathlib import Path

import pandas as pd

from . import crypto
from .budgets import Budget, Limit
from .institutions import SOURCE_PREFIX, STATEMENT_PREFIX, source_key, statement_key
from .models import Email, Institution, Order, StatementBatch, Transaction
from .rules import Rule, split_words

# How close in time two same-amount orders from different sources must be to count as one.
TWIN_WINDOW = dt.timedelta(hours=3)
# A statement lists a transaction by date, sometimes the posting date a day or
# two after the alert, so a statement row and an alert match within this window.
STATEMENT_TWIN_WINDOW = dt.timedelta(days=3)
# Something the user added or pasted carries the day they gave, not the exact time.
TYPED_TWIN_WINDOW = dt.timedelta(days=1)
# Transactions the user added: typed in, or pasted from a bank's SMS or app notification.
TYPED_SOURCES = ("manual", "message")
CASH = "cash"  # the "account" of an expense paid in cash


def _has_order_number(order_key: str) -> bool:
    """Keys built from an email id or a CSV row hash carry no real order number."""
    return ":msg:" not in order_key and ":csv:" not in order_key


_SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    order_key   TEXT PRIMARY KEY,
    provider    TEXT NOT NULL,
    order_date  TEXT NOT NULL,      -- ISO 8601, UTC
    amount      REAL NOT NULL,
    currency    TEXT NOT NULL,
    merchant    TEXT,
    category    TEXT,
    source      TEXT NOT NULL,      -- 'gmail', 'csv' or 'account'
    subject     TEXT,
    message_id  TEXT,
    account     TEXT
);
CREATE TABLE IF NOT EXISTS institutions (
    key                TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    kind               TEXT NOT NULL,    -- 'bank', 'wallet' or 'card'
    sender_terms       TEXT NOT NULL,    -- comma-separated
    subject_terms      TEXT NOT NULL DEFAULT '',
    currency           TEXT NOT NULL DEFAULT 'PKR',
    enabled            INTEGER NOT NULL DEFAULT 1,
    statements         INTEGER NOT NULL DEFAULT 1,
    statement_password TEXT NOT NULL DEFAULT '',  -- encrypted
    statement_senders  TEXT NOT NULL DEFAULT '',
    statement_subjects TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS transactions (
    txn_key       TEXT PRIMARY KEY,
    institution   TEXT NOT NULL,
    txn_date      TEXT NOT NULL,    -- ISO 8601, UTC
    amount        REAL NOT NULL,    -- positive
    currency      TEXT NOT NULL,
    direction     TEXT NOT NULL,    -- 'debit' or 'credit'
    description   TEXT,
    category      TEXT,
    reference     TEXT,
    account_hint  TEXT,
    source        TEXT NOT NULL,    -- 'gmail' (alert), 'statement', 'manual' (typed in) or 'message' (pasted)
    subject       TEXT,
    message_id    TEXT,
    account       TEXT,
    matched_order TEXT,             -- order this payment is for, set by reconcile
    transfer_id   TEXT,             -- shared by both legs of a move between own accounts
    statement_ref TEXT              -- on an alert: the statement row it also appears as
);
CREATE TABLE IF NOT EXISTS statements (
    message_id    TEXT PRIMARY KEY,
    institution   TEXT NOT NULL,
    received_at   TEXT NOT NULL,
    subject       TEXT,
    files         TEXT,
    period_start  TEXT,
    period_end    TEXT,
    rows_found    INTEGER NOT NULL,
    rows_added    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS category_overrides (
    item     TEXT PRIMARY KEY,      -- 'order:<order_key>' or 'txn:<txn_key>'
    category TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_details (
    item      TEXT PRIMARY KEY,     -- as in category_overrides
    spent_for TEXT,                 -- who it was for, e.g. 'Mine' or 'Home'
    note      TEXT,
    counted   INTEGER               -- 1/0 when the user ticked or unticked "In spending"
);
CREATE TABLE IF NOT EXISTS rules (
    position    INTEGER PRIMARY KEY,
    words       TEXT NOT NULL DEFAULT '',  -- comma-separated
    category_is TEXT NOT NULL DEFAULT '',
    min_amount  REAL,
    max_amount  REAL,
    category    TEXT NOT NULL DEFAULT '',
    spent_for   TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS budgets (
    from_month TEXT NOT NULL,           -- 'YYYY-MM': applies from this month until a later one
    position   INTEGER NOT NULL,        -- 0 is the whole month; limits follow
    name       TEXT NOT NULL DEFAULT '',
    category   TEXT NOT NULL DEFAULT '',
    words      TEXT NOT NULL DEFAULT '',  -- comma-separated
    amount     REAL,                    -- NULL on position 0 when there's no total
    PRIMARY KEY (from_month, position)
);
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id  TEXT NOT NULL,
    provider    TEXT NOT NULL,      -- delivery service key, 'acct:<key>' or 'stmt:<key>'
    status      TEXT NOT NULL,      -- 'added', 'duplicate' or 'skipped'
    reason      TEXT,
    subject     TEXT,
    sender      TEXT,
    received_at TEXT,
    account     TEXT,
    PRIMARY KEY (provider, message_id)
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

# Columns added after the first release, for databases created before them.
_ADDED_COLUMNS = {
    "institutions": [
        "statements INTEGER NOT NULL DEFAULT 1",
        "statement_password TEXT NOT NULL DEFAULT ''",
        "statement_senders TEXT NOT NULL DEFAULT ''",
        "statement_subjects TEXT NOT NULL DEFAULT ''",
    ],
    "transactions": ["statement_ref TEXT"],
}


class OrderStore:
    def __init__(self, path: Path):
        self.conn = sqlite3.connect(path)
        self.conn.executescript(_SCHEMA)
        self._upgrade()

    def close(self) -> None:
        self.conn.close()

    def _upgrade(self) -> None:
        for table, columns in _ADDED_COLUMNS.items():
            existing = {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}
            for column in columns:
                if column.split()[0] not in existing:
                    self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column}")
        # The same email can now be read by two sources (alerts and statements),
        # so processed messages are keyed by source as well.
        key_columns = [row[1] for row in self.conn.execute("PRAGMA table_info(processed_messages)") if row[5]]
        if key_columns == ["message_id"]:
            self.conn.executescript("""
                ALTER TABLE processed_messages RENAME TO processed_messages_old;
                CREATE TABLE processed_messages (
                    message_id TEXT NOT NULL, provider TEXT NOT NULL, status TEXT NOT NULL,
                    reason TEXT, subject TEXT, sender TEXT, received_at TEXT, account TEXT,
                    PRIMARY KEY (provider, message_id)
                );
                INSERT INTO processed_messages
                    SELECT message_id, provider, status, reason, subject, sender, received_at, account
                    FROM processed_messages_old;
                DROP TABLE processed_messages_old;
            """)
        self.conn.commit()

    # --- orders ---

    def add_order(self, order: Order, account: str = "") -> bool:
        """Insert an order; returns False if it is already stored.

        "Already stored" means the same order key, or, when either side lacks an
        order number, an order from a different source (Gmail, CSV, account)
        for the same service and amount within TWIN_WINDOW.
        """
        if self._has_twin(order):
            return False
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO orders VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                order.order_key, order.provider, order.order_date.astimezone(dt.UTC).isoformat(),
                order.amount, order.currency, order.merchant, order.category, order.source,
                order.subject, order.message_id, account,
            ),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def _has_twin(self, order: Order) -> bool:
        when = order.order_date.astimezone(dt.UTC)
        row = self.conn.execute(
            "SELECT 1 FROM orders WHERE provider = ? AND currency = ? AND ABS(amount - ?) < 0.005 "
            "AND source != ? AND order_date BETWEEN ? AND ? "
            "AND (? OR order_key LIKE '%:msg:%' OR order_key LIKE '%:csv:%') LIMIT 1",
            (
                order.provider, order.currency, order.amount, order.source,
                (when - TWIN_WINDOW).isoformat(), (when + TWIN_WINDOW).isoformat(),
                not _has_order_number(order.order_key),
            ),
        ).fetchone()
        return row is not None

    def orders_frame(self) -> pd.DataFrame:
        df = pd.read_sql_query("SELECT * FROM orders ORDER BY order_date DESC", self.conn)
        df["order_date"] = pd.to_datetime(df["order_date"], utc=True, format="ISO8601")
        return df

    # --- banks and wallets ---

    def institutions(self) -> list[Institution]:
        rows = self.conn.execute(
            "SELECT key, name, kind, sender_terms, subject_terms, currency, enabled, statements, "
            "statement_password, statement_senders, statement_subjects "
            "FROM institutions ORDER BY name COLLATE NOCASE"
        ).fetchall()
        return [
            Institution(
                key, name, kind, _split(senders), _split(subjects), currency, bool(enabled),
                bool(statements), crypto.decrypt(password), _split(st_senders), _split(st_subjects),
            )
            for (key, name, kind, senders, subjects, currency, enabled, statements, password,
                 st_senders, st_subjects) in rows
        ]

    def save_institution(self, institution: Institution) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO institutions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                institution.key, institution.name, institution.kind,
                ", ".join(institution.sender_terms), ", ".join(institution.subject_terms),
                institution.currency, int(institution.enabled), int(institution.statements),
                crypto.encrypt(institution.statement_password),
                ", ".join(institution.statement_senders), ", ".join(institution.statement_subjects),
            ),
        )
        self.conn.commit()

    def delete_institution(self, key: str) -> None:
        """Remove a bank or wallet together with everything read from its emails."""
        self.conn.execute("DELETE FROM institutions WHERE key = ?", (key,))
        self.conn.execute("DELETE FROM transactions WHERE institution = ?", (key,))
        self.conn.execute("DELETE FROM statements WHERE institution = ?", (key,))
        self.conn.execute(
            "DELETE FROM processed_messages WHERE provider IN (?, ?)", (source_key(key), statement_key(key))
        )
        self.conn.commit()

    # --- transactions ---

    def add_transaction(self, txn: Transaction, account: str = "") -> bool:
        """Insert a transaction; returns False if it is already stored.

        An alert and a statement row for the same money movement are stored
        once: the alert is kept (it has the exact time) and remembers the
        statement row it stands for, so re-reading the statement adds nothing.
        Something the user added or pasted counts as an alert here, and an
        email alert for a payment the user already added isn't stored again.
        """
        if txn.source == "statement":
            if self.conn.execute("SELECT 1 FROM transactions WHERE statement_ref = ?", (txn.txn_key,)).fetchone():
                return False
            alert = self._twin(txn, _ALERTS)
            if alert:
                self.conn.execute("UPDATE transactions SET statement_ref = ? WHERE txn_key = ?", (txn.txn_key, alert))
                self.conn.commit()
                return False
            return self._insert(txn, account)
        if txn.source == "gmail" and self._twin(txn, _TYPED, TYPED_TWIN_WINDOW):
            return False

        statement_row = self._twin(txn, _STATEMENT_ROWS)
        added = self._insert(txn, account, statement_ref=statement_row)
        if added and statement_row:
            self.conn.execute("DELETE FROM transactions WHERE txn_key = ?", (statement_row,))
            self.conn.commit()
        return added

    def _insert(self, txn: Transaction, account: str, statement_ref: str | None = None) -> bool:
        cursor = self.conn.execute(
            "INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL,NULL,?)",
            (
                txn.txn_key, txn.institution, txn.txn_date.astimezone(dt.UTC).isoformat(), txn.amount,
                txn.currency, txn.direction, txn.description, txn.category, txn.reference,
                txn.account_hint, txn.source, txn.subject, txn.message_id, account, statement_ref,
            ),
        )
        self.conn.commit()
        return cursor.rowcount == 1

    def _twin(self, txn: Transaction, kind: str, window: dt.timedelta = STATEMENT_TWIN_WINDOW) -> str | None:
        """The closest stored transaction of `kind` (an SQL condition) that is the same money movement."""
        when = txn.txn_date.astimezone(dt.UTC)
        row = self.conn.execute(
            f"SELECT txn_key FROM transactions WHERE {kind} AND institution = ? AND direction = ? "
            "AND currency = ? AND ABS(amount - ?) < 0.005 AND txn_date BETWEEN ? AND ? "
            "ORDER BY ABS(julianday(txn_date) - julianday(?)) LIMIT 1",
            (
                txn.institution, txn.direction, txn.currency, txn.amount,
                (when - window).isoformat(), (when + window).isoformat(), when.isoformat(),
            ),
        ).fetchone()
        return row[0] if row else None

    # --- transactions the user added ---

    def add_typed(self, txn: Transaction) -> bool:
        """Store a transaction the user typed in (source 'manual') or pasted ('message')."""
        if txn.source not in TYPED_SOURCES:
            raise ValueError(txn.source)
        if txn.source == "manual" and not txn.txn_key:
            txn.txn_key = f"{txn.institution}:manual:{uuid.uuid4().hex[:12]}"
        return self.add_transaction(txn)

    def already_tracked(self, txn: Transaction) -> str | None:
        """A stored transaction that looks like the same payment, to warn before adding it twice."""
        return self._twin(txn, "1", TYPED_TWIN_WINDOW)

    def transaction(self, txn_key: str) -> dict | None:
        cursor = self.conn.execute("SELECT * FROM transactions WHERE txn_key = ?", (txn_key,))
        row = cursor.fetchone()
        return dict(zip([c[0] for c in cursor.description], row)) if row else None

    def update_typed(self, txn_key: str, when: dt.datetime, amount: float, description: str, institution: str) -> None:
        self.conn.execute(
            "UPDATE transactions SET txn_date = ?, amount = ?, description = ?, institution = ? "
            f"WHERE txn_key = ? AND source IN {TYPED_SOURCES}",
            (when.astimezone(dt.UTC).isoformat(), amount, description, institution, txn_key),
        )
        self.conn.commit()

    def delete_typed(self, txn_key: str) -> None:
        """Remove a transaction the user added, with their edits to it."""
        if self.conn.execute(f"DELETE FROM transactions WHERE txn_key = ? AND source IN {TYPED_SOURCES}",
                             (txn_key,)).rowcount:
            for table in ("category_overrides", "item_details"):
                self.conn.execute(f"DELETE FROM {table} WHERE item = ?", (f"txn:{txn_key}",))
        self.conn.commit()

    def transactions_frame(self) -> pd.DataFrame:
        df = pd.read_sql_query("SELECT * FROM transactions ORDER BY txn_date DESC", self.conn)
        df["txn_date"] = pd.to_datetime(df["txn_date"], utc=True, format="ISO8601")
        return df

    def set_reconciliation(self, matches: dict[str, str], transfers: dict[str, str]) -> None:
        """Replace all order links and transfer pairs with a freshly computed set."""
        self.conn.execute("UPDATE transactions SET matched_order = NULL, transfer_id = NULL")
        self.conn.executemany(
            "UPDATE transactions SET matched_order = ? WHERE txn_key = ?",
            [(order, txn) for txn, order in matches.items()],
        )
        self.conn.executemany(
            "UPDATE transactions SET transfer_id = ? WHERE txn_key = ?",
            [(transfer, txn) for txn, transfer in transfers.items()],
        )
        self.conn.commit()

    # --- monthly statements ---

    def add_statement(self, batch: StatementBatch, account: str = "") -> int:
        """Store a statement's transactions; returns how many were new."""
        added = sum(self.add_transaction(txn, account) for txn in batch.transactions)
        self.conn.execute(
            "INSERT OR REPLACE INTO statements VALUES (?,?,?,?,?,?,?,?,?)",
            (
                batch.message_id, batch.institution, batch.received_at.astimezone(dt.UTC).isoformat(),
                batch.subject, ", ".join(batch.files),
                batch.period_start.isoformat() if batch.period_start else None,
                batch.period_end.isoformat() if batch.period_end else None,
                len(batch.transactions), added,
            ),
        )
        self.conn.commit()
        return added

    def statement_transactions(self) -> pd.DataFrame:
        """Every transaction a statement lists: its own rows plus the alerts they matched.

        `statement_id` is the statement email's message id.
        """
        df = self.transactions_frame()
        df = df[(df["source"] == "statement") | df["statement_ref"].notna()].copy()
        # A statement row's key, and an alert's statement_ref, are "<institution>:stmt:<message id>:<row>".
        row_key = df["txn_key"].where(df["source"] == "statement", df["statement_ref"])
        df["statement_id"] = row_key.str.split(":stmt:").str[1].str.rsplit(":", n=1).str[0]
        return df

    def statements_frame(self) -> pd.DataFrame:
        df = pd.read_sql_query(
            "SELECT institution, period_start, period_end, received_at, subject, files, rows_found, rows_added "
            "FROM statements ORDER BY COALESCE(period_end, received_at) DESC",
            self.conn,
        )
        df["received_at"] = pd.to_datetime(df["received_at"], utc=True, format="ISO8601")
        for column in ("period_start", "period_end"):
            df[column] = pd.to_datetime(df[column]).dt.date
        return df

    def retry_unread_statements(self, institution_key: str) -> None:
        """Forget statements that couldn't be read (e.g. locked) so the next sync tries again."""
        self.conn.execute(
            "DELETE FROM processed_messages WHERE provider = ? AND status = 'skipped'",
            (statement_key(institution_key),),
        )
        self.conn.commit()

    # --- edits to single items: category, who it was for, note, In spending ---

    def category_overrides(self) -> dict[str, str]:
        return dict(self.conn.execute("SELECT item, category FROM category_overrides").fetchall())

    def set_category(self, item: str, category: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO category_overrides VALUES (?, ?)", (item, category))
        self.conn.commit()

    def item_details(self) -> pd.DataFrame:
        """Who each item was for, its note, and "In spending" choices, indexed by item."""
        return pd.read_sql_query("SELECT * FROM item_details", self.conn, index_col="item")

    def set_item_detail(self, item: str, field: str, value: str | bool | None) -> None:
        if field not in ("spent_for", "note", "counted"):
            raise ValueError(field)
        value = int(value) if isinstance(value, bool) else value
        self.conn.execute("INSERT OR IGNORE INTO item_details (item) VALUES (?)", (item,))
        self.conn.execute(f"UPDATE item_details SET {field} = ? WHERE item = ?", (value, item))
        self.conn.commit()

    # --- the user's category rules ---

    def rules(self) -> list[Rule]:
        rows = self.conn.execute(
            "SELECT words, category_is, min_amount, max_amount, category, spent_for FROM rules ORDER BY position"
        ).fetchall()
        return [Rule(split_words(words), *rest) for words, *rest in rows]

    def save_rules(self, rules: list[Rule]) -> None:
        self.conn.execute("DELETE FROM rules")
        self.conn.executemany(
            "INSERT INTO rules VALUES (?,?,?,?,?,?,?)",
            [(i, ", ".join(r.words), r.category_is, r.min_amount, r.max_amount, r.category, r.spent_for)
             for i, r in enumerate(rules)],
        )
        self.conn.commit()

    # --- budgets ---

    def budgets(self) -> dict[str, Budget]:
        """Every saved budget, by the month it applies from ('YYYY-MM')."""
        saved: dict[str, Budget] = {}
        rows = self.conn.execute(
            "SELECT from_month, position, name, category, words, amount FROM budgets ORDER BY from_month, position"
        )
        for month, position, name, category, words, amount in rows:
            budget = saved.setdefault(month, Budget())
            if position == 0:
                budget.total = amount
            else:
                budget.limits.append(Limit(name, amount, category, split_words(words)))
        return saved

    def save_budget(self, month: str, budget: Budget) -> None:
        """Save the budget that applies from `month` ('YYYY-MM') on."""
        self.conn.execute("DELETE FROM budgets WHERE from_month = ?", (month,))
        self.conn.executemany(
            "INSERT INTO budgets VALUES (?,?,?,?,?,?)",
            [(month, 0, "", "", "", budget.total)]
            + [(month, i, limit.name, limit.category, ", ".join(limit.words), limit.amount)
               for i, limit in enumerate(budget.limits, start=1)],
        )
        self.conn.commit()

    # --- processed Gmail messages ---

    def processed_ids(self, provider: str) -> set[str]:
        """Message ids this source has already read."""
        return {
            row[0] for row in
            self.conn.execute("SELECT message_id FROM processed_messages WHERE provider = ?", (provider,))
        }

    def mark_processed(
        self, email: Email, provider: str, status: str, reason: str, account: str = ""
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO processed_messages VALUES (?,?,?,?,?,?,?,?)",
            (
                email.message_id, provider, status, reason, email.subject, email.sender,
                email.received_at.isoformat(), account,
            ),
        )
        self.conn.commit()

    def skipped_frame(self) -> pd.DataFrame:
        df = pd.read_sql_query(
            "SELECT received_at, provider, subject, sender, reason FROM processed_messages "
            "WHERE status = 'skipped' ORDER BY received_at DESC",
            self.conn,
        )
        df["received_at"] = pd.to_datetime(df["received_at"], utc=True, format="ISO8601")
        return df

    def forget_gmail_data(self, source_keys: list[str]) -> None:
        """Drop email-sourced records and processed markers so the next sync re-reads them.

        `source_keys` are delivery service keys, 'acct:<key>' and/or 'stmt:<key>'.
        Alerts and statements of one bank are linked, so forgetting either
        forgets both.
        """
        institutions = {
            key[len(prefix):] for key in source_keys
            for prefix in (SOURCE_PREFIX, STATEMENT_PREFIX) if key.startswith(prefix)
        }
        keys = set(source_keys) | {source_key(i) for i in institutions} | {statement_key(i) for i in institutions}
        marks = ",".join("?" * len(keys))
        self.conn.execute(f"DELETE FROM orders WHERE source = 'gmail' AND provider IN ({marks})", list(keys))
        if institutions:
            inst_marks = ",".join("?" * len(institutions))
            self.conn.execute(
                f"DELETE FROM transactions WHERE source IN ('gmail', 'statement') AND institution IN ({inst_marks})",
                list(institutions),
            )
            self.conn.execute(f"DELETE FROM statements WHERE institution IN ({inst_marks})", list(institutions))
        self.conn.execute(f"DELETE FROM processed_messages WHERE provider IN ({marks})", list(keys))
        self.conn.commit()

    # --- settings and sync bookkeeping ---

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (f"setting:{key}",)).fetchone()
        return row[0] if row else default

    def set_setting(self, key: str, value: str) -> None:
        self.conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (f"setting:{key}", value))
        self.conn.commit()

    def last_sync(self) -> dt.datetime | None:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'last_sync'").fetchone()
        return dt.datetime.fromisoformat(row[0]) if row else None

    def set_last_sync(self, when: dt.datetime) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO meta VALUES ('last_sync', ?)", (when.isoformat(),)
        )
        self.conn.commit()


_ALERTS = "source != 'statement' AND statement_ref IS NULL"
_STATEMENT_ROWS = "source = 'statement'"
_TYPED = f"source IN {TYPED_SOURCES}"


def _split(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]
