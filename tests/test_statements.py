"""Reading statement PDFs and statement emails."""

import datetime as dt

import pytest

from order_tracker.models import Attachment, Email, Institution
from order_tracker.statements import (
    StatementLockedError, parse_amount, parse_date, parse_statement, read_statement_email,
)
from tests.statement_pdfs import bank_statement, card_statement, headerless_statement

SEP = dt.date(2026, 9, 30)


@pytest.mark.parametrize("text, expected", [
    ("02-Sep-2026", dt.date(2026, 9, 2)),
    ("02 SEP 26", dt.date(2026, 9, 2)),
    ("02/09/2026", dt.date(2026, 9, 2)),
    ("02.09.26", dt.date(2026, 9, 2)),
    ("2026-09-02", dt.date(2026, 9, 2)),
    ("Sep 02, 2026", dt.date(2026, 9, 2)),
    ("September 2 2026", dt.date(2026, 9, 2)),
    ("02 Sep", dt.date(2026, 9, 2)),  # year from the reference date
    ("28 Dec", dt.date(2025, 12, 28)),  # January statement listing December
    ("POS 12", None),
    ("31-Feb-2026", None),
])
def test_parse_date(text, expected):
    reference = dt.date(2026, 1, 5) if text == "28 Dec" else SEP
    assert parse_date(text, reference) == expected


@pytest.mark.parametrize("text, expected", [
    ("1,884.99", (1884.99, None)),
    ("50,000.00CR", (50000.0, "CR")),
    ("(1,200.00)", (-1200.0, None)),
    ("-450.00", (-450.0, None)),
    ("10456321", None),  # cheque number: no decimals
    ("2026", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_bank_statement_with_debit_and_credit_columns():
    statement = parse_statement(bank_statement())
    assert (statement.period_start, statement.period_end) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    rows = [(r.date.day, r.description, r.amount, r.direction) for r in statement.rows]
    assert rows == [
        (2, "POS FOODPANDA PK", 1884.99, "debit"),
        (3, "IBFT TO AHMED KHAN REF 7712345 MOBILE APP", 5000.0, "debit"),
        (5, "CHEQUE PAID 10456321", 12000.0, "debit"),
        (25, "SALARY ACME TECHNOLOGIES", 285000.0, "credit"),
        (28, "K-ELECTRIC BILL PAYMENT", 14250.5, "debit"),
    ]
    assert statement.rows[-1].balance == 303864.51


def test_card_statement_with_one_amount_column():
    rows = parse_statement(card_statement(), kind="card").rows
    assert [(r.date, r.description, r.amount, r.direction) for r in rows] == [
        (dt.date(2026, 9, 7), "NETFLIX.COM", 2800.0, "debit"),
        (dt.date(2026, 9, 12), "PAYMENT RECEIVED - THANK YOU", 50000.0, "credit"),
        (dt.date(2026, 9, 20), "DARAZ.PK", 6499.0, "debit"),
        (dt.date(2026, 9, 25), "REFUND DARAZ.PK", 1200.0, "credit"),
    ]


def test_statement_without_a_header_uses_the_running_balance():
    statement = parse_statement(headerless_statement())
    assert [(r.date, r.amount, r.direction) for r in statement.rows] == [
        (dt.date(2026, 9, 2), 2500.0, "debit"),
        (dt.date(2026, 9, 4), 3000.0, "credit"),
        (dt.date(2026, 9, 6), 5000.0, "debit"),
    ]


def test_password_protected_statement():
    locked = bank_statement(password="4321")
    with pytest.raises(StatementLockedError):
        parse_statement(locked)
    with pytest.raises(StatementLockedError):
        parse_statement(locked, password="0000")
    assert len(parse_statement(locked, password="4321").rows) == 5


# --- statement emails ---

MEEZAN = Institution("meezan", "Meezan Bank", "bank", ["meezan"])
RECEIVED = dt.datetime(2026, 10, 2, 6, 0, tzinfo=dt.UTC)


def email(*attachments: Attachment) -> Email:
    return Email("m1", "Meezan Bank <estatement@meezanbank.com>", "Your e-Statement for September 2026",
                 RECEIVED, ["Please find attached your statement."], list(attachments))


def test_statement_email_becomes_transactions():
    batch, reason = read_statement_email(email(Attachment("Sep-2026.pdf", "application/pdf", bank_statement())), MEEZAN)
    assert reason == ""
    assert (batch.period_start, batch.period_end, batch.files) == (dt.date(2026, 9, 1), dt.date(2026, 9, 30), ["Sep-2026.pdf"])
    first = batch.transactions[0]
    assert first.txn_key == "meezan:stmt:m1:0"
    assert (first.source, first.currency, first.category) == ("statement", "PKR", "Food")
    assert first.txn_date.astimezone(dt.datetime.now().astimezone().tzinfo).date() == dt.date(2026, 9, 2)
    assert batch.transactions[3].category == "Income"


def test_locked_statement_asks_for_the_password():
    locked = Attachment("Sep-2026.pdf", "application/pdf", bank_statement(password="4321"))
    batch, reason = read_statement_email(email(locked), MEEZAN)
    assert batch is None and "add the statement password for Meezan Bank" in reason

    wrong = Institution("meezan", "Meezan Bank", "bank", ["meezan"], statement_password="0000")
    assert "didn't open" in read_statement_email(email(locked), wrong)[1]

    right = Institution("meezan", "Meezan Bank", "bank", ["meezan"], statement_password="4321")
    assert len(read_statement_email(email(locked), right)[0].transactions) == 5


def test_statement_email_without_a_pdf():
    batch, reason = read_statement_email(email(), MEEZAN)
    assert batch is None and reason == "no PDF statement attached"
    junk = Attachment("Sep.pdf", "application/pdf", b"not a pdf")
    assert read_statement_email(email(junk), MEEZAN) == (None, "no transactions found in the statement")
