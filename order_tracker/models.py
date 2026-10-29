from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass
class Attachment:
    filename: str
    mime_type: str
    data: bytes


@dataclass
class Email:
    """The parts of a Gmail message the parsers need."""

    message_id: str
    sender: str
    subject: str
    received_at: datetime  # timezone-aware UTC
    bodies: list[str] = field(default_factory=list)  # candidate text bodies, preferred first
    attachments: list[Attachment] = field(default_factory=list)  # PDFs, only fetched for statements


@dataclass
class Order:
    provider: str  # key from order_tracker.parsers.PROVIDERS
    order_key: str  # stable identity used to de-duplicate, e.g. "careem:B-12345"
    order_date: datetime  # timezone-aware UTC
    amount: float  # negative for refunds
    currency: str  # ISO code, e.g. "PKR"
    merchant: str
    category: str  # "Food", "Groceries", "Ride", "Delivery"
    source: str = "gmail"  # "gmail", "csv" or "account"
    subject: str = ""
    message_id: str = ""


@dataclass
class Transaction:
    """One money movement from a bank or wallet alert email or monthly statement."""

    institution: str  # Institution.key
    txn_key: str  # stable identity, e.g. "meezan:FT24123ABC"
    txn_date: datetime  # timezone-aware UTC; statement rows carry midday of their date
    amount: float  # always positive; `direction` says which way the money moved
    currency: str
    direction: str  # "debit" (money out) or "credit" (money in)
    description: str  # merchant, payee or payer as written in the alert or statement
    category: str
    reference: str = ""
    account_hint: str = ""  # last digits of the account or card, when the alert shows them
    source: str = "gmail"  # "gmail" (an alert email) or "statement"
    subject: str = ""
    message_id: str = ""


@dataclass
class StatementBatch:
    """Everything read from one monthly statement email."""

    institution: str
    message_id: str
    received_at: datetime
    subject: str
    files: list[str]
    period_start: date | None
    period_end: date | None
    transactions: list[Transaction]


@dataclass
class Institution:
    """A bank or wallet the user wants tracked, found in Gmail by its sender."""

    key: str
    name: str
    kind: str  # "bank", "wallet" or "card"
    sender_terms: list[str]  # Gmail from: terms: a word, a domain or a full address
    subject_terms: list[str] = field(default_factory=list)  # optional: only read these subjects
    currency: str = "PKR"  # used when an alert shows an amount without a currency
    enabled: bool = True
    # Monthly statements (usually a PDF attachment, often password-protected).
    statements: bool = True
    statement_password: str = ""  # kept encrypted at rest
    statement_senders: list[str] = field(default_factory=list)  # empty: same senders as the alerts
    statement_subjects: list[str] = field(default_factory=list)  # empty: subjects mentioning "statement"
