"""Shared receipt-parsing logic.

Each service subclasses Provider and mostly just declares data: which Gmail
senders to search, which labels precede the order total, and how to name the
merchant. The heavy lifting (finding "<label> ... <currency> <amount>" in
free text) lives here so every parser behaves the same way.
"""

import re
from collections.abc import Sequence

from ..email_utils import strip_forward_wrapper
from ..models import Email, Order

CURRENCY_CODES = {
    "pkr": "PKR", "rs": "PKR", "rs.": "PKR", "₨": "PKR",
    "aed": "AED", "sar": "SAR", "qar": "QAR", "kwd": "KWD", "bhd": "BHD",
    "omr": "OMR", "jod": "JOD", "egp": "EGP",
    "bdt": "BDT", "tk": "BDT", "৳": "BDT",
    "usd": "USD", "$": "USD",
}

CURRENCY = r"(?<![A-Za-z])(?:PKR|Rs\.?|₨|AED|SAR|QAR|KWD|BHD|OMR|JOD|EGP|BDT|Tk|৳|USD|\$)(?![A-Za-z])"
NUMBER = r"-?\d[\d,]*(?:\.\d+)?"
MONEY = (
    rf"(?:(?P<cur1>{CURRENCY})\s*(?P<amt1>{NUMBER})"
    rf"|(?P<amt2>{NUMBER})\s*(?P<cur2>{CURRENCY}))"
)
# Between a label and its amount: at most three short lines, which covers both
# "Total: PKR 450" and HTML tables flattened to "Total\nPKR\n450".
_GAP = r"[^\n]{0,40}?(?:\n[^\n]{0,40}?){0,2}?"

# A bare "Total" that is not "Total savings", "Total items", etc.
TOTAL = r"total(?!\s*(?:savings?|saved|discounts?|items?|distance|time|km))"

DEFAULT_SKIP_SUBJECT_TERMS = (
    "cancel", "otp", "verification", "verify", "password", "sign in", "sign-in",
    "login", "log in", "welcome", "% off", "promo", "offer", "deal", "discount",
    "newsletter",
)

_ORDER_REF = re.compile(
    r"(?<![A-Za-z])(?:order|booking|trip|ride|invoice)\s*"
    r"(?:#|no\.?|number|id|reference|ref\.?|code)\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{3,})",
    re.IGNORECASE,
)


def normalize_currency(raw: str) -> str:
    return CURRENCY_CODES.get(raw.strip().lower(), raw.strip().upper())


def parse_number(raw: str) -> float:
    return float(raw.replace(",", ""))


def find_total(text: str, labels: Sequence[str]) -> tuple[float, str] | None:
    """Return (amount, currency) for the first label, in priority order, that is
    followed closely by a currency amount."""
    for label in labels:
        pattern = re.compile(rf"(?<![A-Za-z]){label}(?![A-Za-z]){_GAP}{MONEY}", re.IGNORECASE)
        match = pattern.search(text)
        if match:
            amount = match.group("amt1") or match.group("amt2")
            currency = match.group("cur1") or match.group("cur2")
            return parse_number(amount), normalize_currency(currency)
    return None


def find_money(text: str) -> tuple[float, str] | None:
    """Return the first currency amount anywhere in text (used for CSV cells)."""
    match = re.search(MONEY, text, re.IGNORECASE)
    if not match:
        return None
    amount = match.group("amt1") or match.group("amt2")
    currency = match.group("cur1") or match.group("cur2")
    return parse_number(amount), normalize_currency(currency)


def find_order_ref(text: str) -> str | None:
    """Order/booking number, used so two emails about one order count once."""
    for match in _ORDER_REF.finditer(text):
        ref = match.group(1)
        if any(ch.isdigit() for ch in ref):
            return ref.upper()
    return None


class Provider:
    key = ""
    name = ""
    # Terms for Gmail's from: operator. "careem" matches both the display name
    # "Careem" and addresses like noreply@careem.com.
    sender_terms: tuple[str, ...] = ()
    # Regex fragments, highest priority first.
    total_labels: tuple[str, ...] = (r"grand\s+total", r"order\s+total", TOTAL)
    skip_subject_terms: tuple[str, ...] = DEFAULT_SKIP_SUBJECT_TERMS

    @property
    def gmail_query(self) -> str:
        return "from:(" + " OR ".join(self.sender_terms) + ")"

    def describe(self, email: Email, body: str, currency: str) -> tuple[str, str]:
        """Return (merchant, category) for a recognised receipt."""
        raise NotImplementedError

    def parse(self, email: Email) -> tuple[Order | None, str]:
        """Return (order, "") for a receipt, or (None, reason) for anything else."""
        subject = email.subject.lower()
        refund = "refund" in subject
        if not refund and any(term in subject for term in self.skip_subject_terms):
            return None, "subject looks like a promotion, cancellation or account email"

        for raw in email.bodies:
            body = strip_forward_wrapper(raw)
            total = find_total(body, self.total_labels)
            if total:
                break
        else:
            return None, "no order total found"

        amount, currency = total
        if refund:
            amount = -abs(amount)
        if amount == 0:
            return None, "order total is zero"

        ref = find_order_ref(body)
        order_key = f"{self.key}:{ref}" if ref else f"{self.key}:msg:{email.message_id}"
        if refund:
            order_key += ":refund"

        merchant, category = self.describe(email, body, currency)
        return Order(
            provider=self.key,
            order_key=order_key,
            order_date=email.received_at,
            amount=amount,
            currency=currency,
            merchant=merchant,
            category=category,
            source="gmail",
            subject=email.subject,
            message_id=email.message_id,
        ), ""
