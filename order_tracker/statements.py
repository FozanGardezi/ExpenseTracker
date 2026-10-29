"""Reading monthly statement emails and the PDF statements attached to them.

Statement layouts differ by bank, so instead of one template per bank this
reads the PDF's words with their positions on the page and looks for the
transaction table:

- A header line naming the columns ("Date ... Debit/Withdrawal ... Credit/
  Deposit ... Balance", or "Date ... Amount" on card statements) gives each
  column's position, and every amount below it goes to the nearest column.
- Each transaction line starts with a date. A following line with text but no
  date or amount continues the previous transaction's description.
- Without a recognisable header, the running balance gives the direction: it
  goes down for money out and up for money in.

Statement amounts always have two decimals ("1,250.00"), which keeps cheque
and reference numbers from being read as amounts.
"""

import datetime as dt
import io
import re
from dataclasses import dataclass

import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from .categories import categorize
from .models import Email, Institution, StatementBatch, Transaction

LOCAL_TZ = dt.datetime.now().astimezone().tzinfo


class StatementLockedError(Exception):
    """The PDF needs a password that wasn't given, or the one given is wrong."""


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float

    @property
    def center(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class StatementRow:
    date: dt.date
    description: str
    amount: float  # positive
    direction: str  # "debit" or "credit"
    balance: float | None = None


@dataclass
class Statement:
    period_start: dt.date | None
    period_end: dt.date | None
    rows: list[StatementRow]


# --- dates ---

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
_MONTH_NAMES = [
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
]
_ISO_DATE = re.compile(r"^(\d{4})[/.\-](\d{1,2})[/.\-](\d{1,2})$")
_NUMERIC_DATE = re.compile(r"^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})$")  # day first
_DAY_MONTH = re.compile(r"^(\d{1,2})[\s/.\-]?([A-Za-z]{3,9})\.?(?:[\s/.\-,]+(\d{4}|\d{2}))?$")
_MONTH_DAY = re.compile(r"^([A-Za-z]{3,9})\.?\s(\d{1,2}),?(?:\s(\d{4}|\d{2}))?$")


def _month_number(name: str) -> int | None:
    name = name.lower()
    number = _MONTHS.get(name[:3])
    if number and (len(name) == 3 or name == "sept" or _MONTH_NAMES[number - 1].startswith(name)):
        return number
    return None


def parse_date(text: str, reference: dt.date | None = None) -> dt.date | None:
    """Parse one date in any common statement format (day first).

    A date without a year takes the reference date's year, or the year before
    when that would put it more than a week after the reference date.
    """
    text = text.strip(" ,;:")
    year = month = day = None
    if m := _ISO_DATE.match(text):
        year, month, day = int(m[1]), int(m[2]), int(m[3])
    elif m := _NUMERIC_DATE.match(text):
        day, month, year = int(m[1]), int(m[2]), int(m[3])
    elif m := _DAY_MONTH.match(text):
        day, month, year = int(m[1]), _month_number(m[2]), m[3] and int(m[3])
    elif m := _MONTH_DAY.match(text):
        month, day, year = _month_number(m[1]), int(m[2]), m[3] and int(m[3])
    if not month or not day:
        return None
    guessed_year = not year
    if guessed_year:
        if reference is None:
            return None
        year = reference.year
    elif year < 100:
        year += 2000
    try:
        date = dt.date(year, month, day)
    except ValueError:
        return None
    if guessed_year and date > reference + dt.timedelta(days=7):
        date = date.replace(year=year - 1)
    return date


def _leading_date(words: list[Word], reference: dt.date | None) -> tuple[dt.date | None, list[Word]]:
    """A date made of the first one to three words, and the words after it."""
    for size in (3, 2, 1):
        if len(words) >= size:
            date = parse_date(" ".join(w.text for w in words[:size]), reference)
            if date:
                return date, words[size:]
    return None, words


def _dates_in(text: str, reference: dt.date | None) -> list[dt.date]:
    tokens = text.split()
    dates, i = [], 0
    while i < len(tokens):
        for size in (3, 2, 1):
            date = parse_date(" ".join(tokens[i:i + size]), reference) if i + size <= len(tokens) else None
            if date:
                dates.append(date)
                i += size
                break
        else:
            i += 1
    return dates


# --- amounts ---

_AMOUNT = re.compile(
    r"^(?P<open>[(-])?(?:Rs\.?|PKR)?(?P<num>\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2})"
    r"(?P<close>[)-])?(?P<marker>CR|DR|Cr|Dr|cr|dr)?$"
)
_MARKER = re.compile(r"^(CR|DR|Cr|Dr|cr|dr)$")


def parse_amount(text: str) -> tuple[float, str | None] | None:
    """(signed value, "CR"/"DR" marker or None) for a statement amount, else None."""
    m = _AMOUNT.match(text.strip())
    if not m:
        return None
    value = float(m["num"].replace(",", ""))
    if m["open"] or m["close"]:
        value = -value
    return value, (m["marker"] or "").upper() or None


@dataclass
class _Amount:
    value: float
    marker: str | None
    center: float


def _split_amounts(words: list[Word]) -> tuple[list[_Amount], list[str]]:
    amounts: list[_Amount] = []
    text: list[str] = []
    for word in words:
        parsed = parse_amount(word.text)
        if parsed:
            amounts.append(_Amount(parsed[0], parsed[1], word.center))
        elif _MARKER.match(word.text) and amounts:
            amounts[-1].marker = word.text.upper()
        else:
            text.append(word.text)
    return amounts, text


# --- table structure ---

_HEADER_WORDS = {
    "date": {"date"},
    "debit": {"debit", "debits", "withdrawal", "withdrawals", "dr", "dr."},
    "credit": {"credit", "credits", "deposit", "deposits", "cr", "cr."},
    "amount": {"amount", "amt"},
    "balance": {"balance", "bal"},
}
_OPENING = re.compile(r"opening balance|balance b/?f|brought forward|previous balance", re.IGNORECASE)
_NOT_A_TRANSACTION = re.compile(
    r"opening balance|closing balance|balance b/?f|balance c/?f|brought forward|carried forward|"
    r"^total|sub ?total|previous balance|minimum (?:amount|payment)|payment due",
    re.IGNORECASE,
)
_CREDIT_WORDS = re.compile(
    r"\b(?:salary|received|deposit|credit|refund|reversal|reversed|cash ?back|profit|inward|transfer from|ibft in)\b",
    re.IGNORECASE,
)


def _header_columns(line: list[Word]) -> dict[str, float] | None:
    """Column positions if this line is the transaction table's header."""
    found: dict[str, float] = {}
    for word in line:
        token = word.text.lower().strip(":()")
        for column, names in _HEADER_WORDS.items():
            if token in names and column not in found:
                found[column] = word.center
    has_both = "debit" in found and "credit" in found
    if "date" not in found or not (has_both or "amount" in found):
        return None
    if has_both:
        found.pop("amount", None)  # "Debit Amount" / "Credit Amount" headers
    found.pop("date")
    return found


def _group_lines(words: list[Word]) -> list[list[Word]]:
    lines: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (round(w.top), w.x0)):
        if lines and abs(lines[-1][0].top - word.top) <= 3:
            lines[-1].append(word)
        else:
            lines.append([word])
    return [sorted(line, key=lambda w: w.x0) for line in lines]


def read_lines(data: bytes, password: str = "") -> list[list[Word]]:
    """The PDF's words, grouped into lines, page by page."""
    try:
        with pdfplumber.open(io.BytesIO(data), password=password or "") as pdf:
            lines: list[list[Word]] = []
            for page in pdf.pages:
                words = [Word(w["text"], w["x0"], w["x1"], w["top"]) for w in page.extract_words()]
                lines.extend(_group_lines(words))
            return lines
    except PdfminerException as exc:
        if any(type(arg).__name__ == "PDFPasswordIncorrect" for arg in exc.args):
            raise StatementLockedError() from exc
        raise


def _direction(amount: _Amount, balance: float | None, previous: float | None,
               description: str, kind: str) -> str:
    if amount.marker == "CR":
        return "credit"
    if amount.marker == "DR":
        return "debit"
    if kind == "card":
        # Card statements list spending as positive and payments or refunds as negative.
        return "credit" if amount.value < 0 else "debit"
    if balance is not None and previous is not None and balance != previous:
        return "credit" if balance > previous else "debit"
    if amount.value < 0:
        return "debit"
    return "credit" if _CREDIT_WORDS.search(description) else "debit"


def _row(date: dt.date, description: str, amounts: list[_Amount], columns: dict[str, float] | None,
         previous_balance: float | None, kind: str) -> StatementRow | None:
    debit = credit = balance = None
    signed: _Amount | None = None
    if columns:
        for amount in amounts:
            column = min(columns, key=lambda c: abs(columns[c] - amount.center))
            if column == "debit":
                debit = abs(amount.value)
            elif column == "credit":
                credit = abs(amount.value)
            elif column == "balance":
                balance = -abs(amount.value) if amount.marker == "DR" else amount.value
            else:
                signed = amount
    elif len(amounts) >= 2:
        # No header: the last amount on a line is the running balance.
        signed, balance = amounts[-2], amounts[-1].value
    else:
        signed = amounts[0]

    if debit and not credit:
        return StatementRow(date, description, debit, "debit", balance)
    if credit and not debit:
        return StatementRow(date, description, credit, "credit", balance)
    if signed and signed.value:
        direction = _direction(signed, balance, previous_balance, description, kind)
        return StatementRow(date, description, abs(signed.value), direction, balance)
    return None


def _period(lines: list[str], received: dt.date | None) -> tuple[dt.date | None, dt.date | None]:
    for text in lines:
        if re.search(r"period|from", text, re.IGNORECASE):
            dates = _dates_in(text, received)
            if len(dates) >= 2 and dates[0] <= dates[1]:
                return dates[0], dates[1]
    return None, None


def parse_statement(data: bytes, password: str = "", kind: str = "bank",
                    received: dt.date | None = None) -> Statement:
    """Read the transactions from one statement PDF."""
    lines = read_lines(data, password)
    texts = [" ".join(w.text for w in line) for line in lines]
    period_start, period_end = _period(texts, received)
    reference = period_end or received

    rows: list[StatementRow] = []
    columns: dict[str, float] | None = None
    previous_balance: float | None = None
    last_row: StatementRow | None = None
    last_top = 0.0
    for line, text in zip(lines, texts):
        header = _header_columns(line)
        if header:
            columns, last_row = header, None
            continue
        date, rest = _leading_date(line, reference)
        if date is None:
            amounts, words = _split_amounts(line)
            if _OPENING.search(text) and amounts:
                previous_balance = amounts[-1].value
            elif last_row and not amounts and words and 0 < line[0].top - last_top <= 16:
                last_row.description = f"{last_row.description} {' '.join(words)}"
                last_top = line[0].top
            continue
        _, rest = _leading_date(rest, reference)  # a second, value-date column
        amounts, words = _split_amounts(rest)
        description = " ".join(words)
        if _OPENING.search(description) and amounts:
            previous_balance = amounts[-1].value
            continue
        if not amounts or _NOT_A_TRANSACTION.search(description):
            last_row = None
            continue
        row = _row(date, description, amounts, columns, previous_balance, kind)
        if row:
            rows.append(row)
            last_row, last_top = row, line[0].top
            if row.balance is not None:
                previous_balance = row.balance
    return Statement(period_start, period_end, rows)


# --- statement emails ---

def _is_pdf(filename: str, mime_type: str) -> bool:
    return filename.lower().endswith(".pdf") or mime_type == "application/pdf"


def read_statement_email(email: Email, institution: Institution) -> tuple[StatementBatch | None, str]:
    """Return the statement's transactions, or (None, reason) when it can't be read."""
    pdfs = [a for a in email.attachments if _is_pdf(a.filename, a.mime_type)]
    if not pdfs:
        return None, "no PDF statement attached"
    received = email.received_at.astimezone(LOCAL_TZ).date()
    statements, files, locked = [], [], False
    for pdf in pdfs:
        try:
            statement = parse_statement(pdf.data, institution.statement_password, institution.kind, received)
        except StatementLockedError:
            locked = True
            continue
        except Exception:  # a damaged or unusual PDF must not stop the sync
            continue
        if statement.rows:
            statements.append(statement)
            files.append(pdf.filename)

    if not statements:
        if locked and institution.statement_password:
            return None, f"the saved statement password for {institution.name} didn't open the PDF"
        if locked:
            return None, f"the PDF is password-protected: add the statement password for {institution.name} on the Statements page"
        return None, "no transactions found in the statement"

    rows = [row for statement in statements for row in statement.rows]
    transactions = [
        Transaction(
            institution=institution.key,
            txn_key=f"{institution.key}:stmt:{email.message_id}:{i}",
            # Statements give dates, not times; midday keeps the date right in any time zone nearby.
            txn_date=dt.datetime.combine(row.date, dt.time(12), tzinfo=LOCAL_TZ).astimezone(dt.UTC),
            amount=row.amount,
            currency=institution.currency,
            direction=row.direction,
            description=row.description,
            category=categorize(row.description, row.direction),
            source="statement",
            subject=email.subject,
            message_id=email.message_id,
        )
        for i, row in enumerate(rows)
    ]
    starts = [s.period_start or min(r.date for r in s.rows) for s in statements]
    ends = [s.period_end or max(r.date for r in s.rows) for s in statements]
    return StatementBatch(
        institution=institution.key,
        message_id=email.message_id,
        received_at=email.received_at,
        subject=email.subject,
        files=files,
        period_start=min(starts),
        period_end=max(ends),
        transactions=transactions,
    ), ""
