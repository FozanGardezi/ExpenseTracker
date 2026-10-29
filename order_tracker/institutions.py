"""Banks and wallets the user tracks, and how their alert emails are found.

Each one is matched in Gmail by its sender. A plain word matches the sender's
name or address ("meezan" matches "Meezan Bank <alerts@meezanbank.com>"), and
a domain or a full address works too. The presets are starting points: if a
bank's alerts are not found, copy the sender from one of its emails into
its settings.
"""

import re

from .alerts import parse_alert
from .models import Email, Institution, StatementBatch, Transaction
from .statements import read_statement_email

SOURCE_PREFIX = "acct:"  # a bank's or wallet's alert emails
STATEMENT_PREFIX = "stmt:"  # its monthly statement emails
DEFAULT_STATEMENT_SUBJECTS = ["statement", "estatement"]  # "statement" also matches "e-Statement"

PRESETS: list[Institution] = [
    Institution("hbl", "HBL", "bank", ["hbl"]),
    Institution("meezan", "Meezan Bank", "bank", ["meezanbank", "meezan"]),
    Institution("ubl", "UBL", "bank", ["ubl"]),
    Institution("mcb", "MCB Bank", "bank", ["mcb"]),
    Institution("alfalah", "Bank Alfalah", "bank", ["bankalfalah", "alfalah"]),
    Institution("abl", "Allied Bank", "bank", ["abl", "alliedbank"]),
    Institution("bankalhabib", "Bank AL Habib", "bank", ["bankalhabib"]),
    Institution("faysal", "Faysal Bank", "bank", ["faysalbank"]),
    Institution("askari", "Askari Bank", "bank", ["askaribank"]),
    Institution("scb", "Standard Chartered", "bank", ["standardchartered", "sc.com"]),
    Institution("jsbank", "JS Bank", "bank", ["jsbl", "jsbank"]),
    Institution("habibmetro", "HabibMetro", "bank", ["habibmetro"]),
    Institution("dib", "Dubai Islamic Bank", "bank", ["dibpak"]),
    Institution("jazzcash", "JazzCash", "wallet", ["jazzcash"]),
    Institution("easypaisa", "Easypaisa", "wallet", ["easypaisa"]),
    Institution("nayapay", "NayaPay", "wallet", ["nayapay"]),
    Institution("sadapay", "SadaPay", "wallet", ["sadapay"]),
    Institution("upaisa", "UPaisa", "wallet", ["upaisa"]),
    Institution("payoneer", "Payoneer", "wallet", ["payoneer"], currency="USD"),
    Institution("paypal", "PayPal", "wallet", ["paypal"], currency="USD"),
    Institution("wise", "Wise", "wallet", ["wise.com"], currency="USD"),
]

KINDS = {"bank": "Bank", "wallet": "Wallet", "card": "Card"}


def make_key(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "", name.lower()) or "account"
    key, n = base, 2
    while key in taken:
        key, n = f"{base}{n}", n + 1
    return key


def split_terms(text: str) -> list[str]:
    return [term.strip() for term in re.split(r"[,\n]", text) if term.strip()]


def _gmail_terms(terms: list[str]) -> str:
    return " OR ".join(f'"{t}"' if " " in t else t for t in terms)


def source_key(institution_key: str) -> str:
    return SOURCE_PREFIX + institution_key


def statement_key(institution_key: str) -> str:
    return STATEMENT_PREFIX + institution_key


class InstitutionSource:
    """Adapts an Institution to the same interface as the delivery-service parsers."""

    def __init__(self, institution: Institution):
        self.institution = institution
        self.key = source_key(institution.key)
        self.name = institution.name

    @property
    def gmail_query(self) -> str:
        query = f"from:({_gmail_terms(self.institution.sender_terms)})"
        if self.institution.subject_terms:
            query += f" subject:({_gmail_terms(self.institution.subject_terms)})"
        return query

    def parse(self, email: Email) -> tuple[Transaction | None, str]:
        return parse_alert(email, self.institution)


class StatementSource:
    """A bank's or wallet's monthly statement emails, read from their PDF attachments."""

    needs_attachments = True

    def __init__(self, institution: Institution):
        self.institution = institution
        self.key = statement_key(institution.key)
        self.name = f"{institution.name} statements"

    @property
    def gmail_query(self) -> str:
        senders = self.institution.statement_senders or self.institution.sender_terms
        subjects = self.institution.statement_subjects or DEFAULT_STATEMENT_SUBJECTS
        return (
            f"from:({_gmail_terms(senders)}) subject:({_gmail_terms(subjects)}) "
            "has:attachment filename:pdf"
        )

    def parse(self, email: Email) -> tuple[StatementBatch | None, str]:
        return read_statement_email(email, self.institution)
