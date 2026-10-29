"""Reading bank and wallet transaction alert emails.

Every bank words its alerts differently, so instead of one template per bank
this looks for what every alert contains:

- the transaction amount (ignoring "available balance" and limit amounts),
- a word saying which way the money moved ("debited", "credited", "sent", ...),
- usually the merchant or person ("at FOODPANDA", "to Ali Khan", "Beneficiary: ...").

Alerts it cannot read are listed on the Skipped emails page with the reason.
The same reading works for a bank's SMS or app notification the user pastes in.
"""

import datetime as dt
import hashlib
import re

from .categories import categorize
from .email_utils import strip_forward_wrapper
from .models import Email, Institution, Transaction
from .parsers.base import MONEY, NUMBER, normalize_currency, parse_number

_SKIP_SUBJECT = re.compile(
    r"\botp\b|one[- ]time|password|\bpin\b|statement|log ?in|sign[- ]?in|verif|declined|"
    r"unsuccessful|failed|not processed|offer|promo|discount|% off|newsletter|survey|welcome",
    re.IGNORECASE,
)

_MONEY = re.compile(MONEY, re.IGNORECASE)
# Text right before an amount that marks it as a balance or limit, not the transaction.
_NOT_TXN_AMOUNT = re.compile(
    r"(?:balance|\bbal\b|\bavl\b|available|limit|outstanding|minimum|\bdue\b|reward|points)[^\n\d]{0,25}$",
    re.IGNORECASE,
)
_NEAR_TXN = re.compile(r"amount|debit|credit|spent|paid|payment|received|sent|transfer|purchase|withdr|charged", re.IGNORECASE)
_LABELLED_AMOUNT = re.compile(rf"\bamount\s*(?:of)?\s*[:\-]?\s*({NUMBER})", re.IGNORECASE)

# "Credit card" and "debit card" say nothing about direction.
_CARD_WORDS = re.compile(r"\b(?:credit|debit)\s+card\b|\bcredit\s+limit\b|\bavailable\s+credit\b", re.IGNORECASE)
_STRONG_DEBIT = re.compile(
    r"\b(?:debited|deducted|withdrawn|spent|purchased?|charged|transferred to|sent to|paid to|paid at|"
    r"payment to|bill payment|used at|used for)\b",
    re.IGNORECASE,
)
_STRONG_CREDIT = re.compile(
    r"\b(?:credited|deposited|received from|payment received|money received|refund(?:ed)?|reversal|"
    r"reversed|cash ?back|salary|transferred from|transfer from)\b",
    re.IGNORECASE,
)
_WEAK_DEBIT = re.compile(r"\b(?:debit|paid|payment|sent|transfer|withdrawal|pos|bill)\b", re.IGNORECASE)
_WEAK_CREDIT = re.compile(r"\b(?:credit|received|deposit|incoming)\b", re.IGNORECASE)

_PARTY_END = (
    r"(?=\s+(?:on|via|ref|reference|dated|using|with|for|from|to|at|in|through|avl|available|bal|"
    r"balance|is|has|was|of)\b|[,;\n(]|\.\s|\.$|\s-\s|$)"
)
_LABELLED_PARTY = re.compile(
    r"\b(?:merchant|beneficiary|receiver|recipient|sender|payee|paid to|received from|description|"
    r"narration|details|biller)(?:\s+name)?\s*[:\-]\s*([^\n]{2,60})",
    re.IGNORECASE,
)
_AT_PARTY = re.compile(rf"\bat\s+([A-Za-z][\w&'*./ -]{{1,50}}?){_PARTY_END}", re.IGNORECASE)
_TO_FROM_PARTY = re.compile(rf"\b(?:to|from)\s+([A-Za-z][\w&'*./ -]{{1,50}}?){_PARTY_END}", re.IGNORECASE)
_NOT_A_PARTY = re.compile(r"^(?:your|you|the|a/c|ac|acc|account|card|mobile|wallet|our|this|bank|online)\b", re.IGNORECASE)

# Money sent to a person or account rather than paid to a merchant.
_TRANSFER_WORDS = re.compile(
    r"\b(?:sent to|transferred to|transfer to|fund transfer|funds transfer|ibft|raast|money sent)\b",
    re.IGNORECASE,
)

_REFERENCE = re.compile(
    r"\b(?:ref(?:erence)?|transaction\s*id|trx\s*id|txn\s*id|tid|rrn|stan|trace)\s*(?:no\.?|number|#|id)?"
    r"\s*[:#.]?\s*([A-Z0-9][A-Z0-9-]{5,})",
    re.IGNORECASE,
)
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*"
# Dates as banks write them in messages: 23-Oct-2026, 23 Oct 26, Oct 23, 2026, 23/10/2026, 2026-10-23.
_DATES = [
    (re.compile(rf"\b(\d{{1,2}})[-/ ]({_MONTH})[-/ ,]+(\d{{2,4}})\b", re.IGNORECASE), "dmy_name"),
    (re.compile(rf"\b({_MONTH})\.? (\d{{1,2}}),? (\d{{4}})\b", re.IGNORECASE), "mdy_name"),
    (re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})\b"), "dmy"),
]
_TIME = re.compile(r"\b(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]\.?m\.?)?(?![\w])", re.IGNORECASE)
_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_ACCOUNT_HINT = re.compile(
    r"(?:a/c|acc(?:ount)?|card)\s*(?:no\.?|number|ending(?:\s+(?:in|with))?)?\s*[:#]?\s*[*xX•.\-]*(\d{3,4})\b",
    re.IGNORECASE,
)


def _find_amount(text: str, default_currency: str) -> tuple[float, str, int, int] | None:
    """Return (amount, currency, start, end) of the transaction amount."""
    candidates = [
        m for m in _MONEY.finditer(text)
        if not _NOT_TXN_AMOUNT.search(text[max(0, m.start() - 35):m.start()])
    ]
    near_words = [m for m in candidates if _NEAR_TXN.search(text[max(0, m.start() - 60):m.end() + 60])]
    chosen = (near_words or candidates or [None])[0]
    if chosen:
        amount = chosen.group("amt1") or chosen.group("amt2")
        currency = chosen.group("cur1") or chosen.group("cur2")
        return abs(parse_number(amount)), normalize_currency(currency), chosen.start(), chosen.end()
    # Some alerts give a bare "Amount: 1,250.00".
    match = _LABELLED_AMOUNT.search(text)
    if match:
        return abs(parse_number(match.group(1))), default_currency, match.start(1), match.end(1)
    return None


def _direction(text: str) -> str | None:
    text = _CARD_WORDS.sub("card", text)
    for debit, credit in ((_STRONG_DEBIT, _STRONG_CREDIT), (_WEAK_DEBIT, _WEAK_CREDIT)):
        d, c = debit.search(text), credit.search(text)
        if d and c:
            return "debit" if d.start() < c.start() else "credit"
        if d or c:
            return "debit" if d else "credit"
    return None


def _party(text: str, window: str) -> str | None:
    match = _LABELLED_PARTY.search(text)
    if match:
        return match.group(1).strip(" .:-")
    for pattern in (_AT_PARTY, _TO_FROM_PARTY):
        for match in pattern.finditer(window):
            value = match.group(1).strip(" .-")
            if value and not _NOT_A_PARTY.match(value):
                return value
    return None


def _reference(text: str) -> str | None:
    for match in _REFERENCE.finditer(text):
        if any(ch.isdigit() for ch in match.group(1)):
            return match.group(1).upper()
    return None


def parse_alert(email: Email, institution: Institution) -> tuple[Transaction | None, str]:
    """Return (transaction, "") for a transaction alert, or (None, reason) for anything else."""
    if _SKIP_SUBJECT.search(email.subject):
        return None, "subject looks like an OTP, statement, promotion or failed transaction"

    for raw in email.bodies or [""]:
        text = f"{email.subject}\n{strip_forward_wrapper(raw)}"
        found = _find_amount(text, institution.currency)
        if found:
            break
    else:
        return None, "no transaction amount found"

    amount, currency, start, end = found
    if amount == 0:
        return None, "transaction amount is zero"
    # Direction and party come from the text around the amount, not the footer.
    window = text[max(0, start - 200):end + 200]
    direction = _direction(email.subject) or _direction(window)
    if direction is None:
        return None, "could not tell whether money went out or came in"

    description = _party(text, window) or email.subject.strip() or institution.name
    reference = _reference(text)
    hint = _ACCOUNT_HINT.search(text)
    key = f"{institution.key}:{reference}" if reference else f"{institution.key}:msg:{email.message_id}"
    # Spending is categorised by the payee; money in also by the words around the
    # amount, since "refund" is rarely in the payee's name.
    category_text = f"{description} {email.subject}" + (f" {window}" if direction == "credit" else "")
    category = categorize(category_text, direction)
    if direction == "debit" and category == "Other" and _TRANSFER_WORDS.search(f"{email.subject} {window}"):
        category = "Transfers"
    return Transaction(
        institution=institution.key,
        txn_key=key,
        txn_date=email.received_at,
        amount=amount,
        currency=currency,
        direction=direction,
        description=description,
        category=category,
        reference=reference or "",
        account_hint=hint.group(1) if hint else "",
        source="gmail",
        subject=email.subject,
        message_id=email.message_id,
    ), ""


def find_date(text: str) -> dt.datetime | None:
    """The date (and time, if given) a bank's message says the transaction happened, as local time."""
    for pattern, order in _DATES:
        match = pattern.search(text)
        if not match:
            continue
        a, b, c = match.groups()
        try:
            if order == "dmy_name":
                day, month, year = int(a), _MONTHS.index(b[:3].lower()) + 1, int(c)
            elif order == "mdy_name":
                day, month, year = int(b), _MONTHS.index(a[:3].lower()) + 1, int(c)
            elif order == "ymd":
                day, month, year = int(c), int(b), int(a)
            else:  # day first, as in Pakistan
                day, month, year = int(a), int(b), int(c)
            day_found = dt.date(year + 2000 if year < 100 else year, month, day)
        except ValueError:
            continue
        clock = _TIME.search(text, match.end()) or _TIME.search(text)
        if not clock:
            return dt.datetime.combine(day_found, dt.time(12))
        hour, minute, half = int(clock.group(1)), int(clock.group(2)), (clock.group(3) or "").lower()
        if half.startswith("p") and hour < 12:
            hour += 12
        elif half.startswith("a") and hour == 12:
            hour = 0
        try:
            return dt.datetime.combine(day_found, dt.time(hour, minute))
        except ValueError:
            return dt.datetime.combine(day_found, dt.time(12))
    return None


def parse_message(text: str, institution: Institution, when: dt.datetime) -> tuple[Transaction | None, str]:
    """Read a bank's or wallet's SMS or app notification that the user pasted in.

    `when` (timezone-aware) is used as the transaction time. Pasting the same
    message twice gives the same key, so it's only stored once.
    """
    digest = hashlib.sha1(" ".join(text.split()).encode()).hexdigest()[:16]
    email = Email(f"sms-{digest}", "", "", when, [text])
    txn, reason = parse_alert(email, institution)
    if txn is None:
        return None, reason.replace("subject looks like", "it looks like")
    txn.source, txn.subject = "message", " ".join(text.split())[:200]
    return txn, ""
