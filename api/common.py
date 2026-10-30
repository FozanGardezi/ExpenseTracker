"""Shared by the API's routes: the signed-in user and their store, the viewer's time
zone, and turning ledger rows into what the app shows.

Screens get their numbers worked out here, with the same order_tracker code the
Streamlit pages use, and display-ready text ("Rs 2.53 lakh", "Yesterday"), so the
phone app only lays them out. Colors and icons are the app's: a category comes
with its color slot (0-4, or None for the shared gray), as on the website.
"""

import datetime as dt
from collections.abc import Iterator
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
from fastapi import Depends, Header, HTTPException

from order_tracker.auth import GmailTokenStore
from order_tracker.budgets import add_months
from order_tracker.config import data_dir, token_key
from order_tracker.insights import months
from order_tracker.institutions import SOURCE_PREFIX, STATEMENT_PREFIX
from order_tracker.ledger import build_ledger
from order_tracker.money import money
from order_tracker.parsers import PROVIDERS
from order_tracker.sessions import SessionStore
from order_tracker.storage import OrderStore
from order_tracker.users import User, user_dir

SLOTS = 5  # categories with a color of their own; the rest share the gray
EVERYTHING_ELSE = "Everything else"
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo
PERIODS = ["This month", "Last month", "Last 3 months", "Last 12 months", "All time", "Custom"]


# --- who is asking ---

def open_sessions() -> SessionStore:
    return SessionStore(data_dir() / "sessions.db")


def bearer_token(authorization: str | None = Header(default=None)) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip() or None
    return None


def current_user(token: str | None = Depends(bearer_token)) -> User:
    sessions = open_sessions()
    try:
        user = sessions.lookup(token)
    finally:
        sessions.close()
    if user is None:
        raise HTTPException(401, "You're signed out. Continue with Google to sign in again.")
    return user


def user_store(user: User = Depends(current_user)) -> Iterator[OrderStore]:
    """The signed-in user's own database, for one request."""
    store = OrderStore(user_dir(user.id) / "orders.db")
    try:
        yield store
    finally:
        store.close()


def gmail_tokens(user: User) -> GmailTokenStore:
    return GmailTokenStore(user_dir(user.id), token_key())


def viewer_tz(x_timezone: str | None = Header(default=None)):
    """The phone's time zone (an IANA name in X-Timezone), which decides where days and months start."""
    try:
        return ZoneInfo(x_timezone) if x_timezone else LOCAL_TZ
    except (ZoneInfoNotFoundError, ValueError):
        return LOCAL_TZ


def today_in(tz) -> dt.date:
    return dt.datetime.now(tz).date()


# --- months and periods ---

def month_key(month: dt.date) -> str:
    return f"{month:%Y-%m}"


def parse_month(key: str | None) -> dt.date | None:
    try:
        return dt.datetime.strptime(key, "%Y-%m").date() if key else None
    except ValueError:
        return None


def month_label(month: dt.date, today: dt.date) -> str:
    if month == today.replace(day=1):
        return "This month"
    if month == add_months(today, -1):
        return "Last month"
    return f"{month:%B %Y}"


def resolve_period(choice: str | None, first: dt.date, last: dt.date, today: dt.date,
                   start: dt.date | None = None, end: dt.date | None = None,
                   default: str = "Last 12 months") -> tuple[str, dt.date, dt.date]:
    """A period preset (or "Custom" with start and end) as (choice, start, end)."""
    choice = choice if choice in PERIODS else default
    if choice == "This month":
        return choice, today.replace(day=1), today
    if choice == "Last month":
        stop = today.replace(day=1) - dt.timedelta(days=1)
        return choice, stop.replace(day=1), stop
    if choice == "Last 3 months":
        return choice, add_months(today, -2), today
    if choice == "Last 12 months":
        return choice, add_months(today, -11), today
    if choice == "All time":
        return choice, first, max(last, today)
    start, end = start or first, end or last
    return choice, min(start, end), max(start, end)


def span_text(start: dt.date, end: dt.date) -> str:
    return f"{start:%d %b %Y} – {end:%d %b %Y}"


# --- the ledger as the viewer sees it ---

def local_ledger(store: OrderStore, tz) -> pd.DataFrame:
    """Every payment once (see order_tracker.ledger), dated in the viewer's time zone, with its month."""
    ledger = build_ledger(store)
    if ledger.empty:
        return ledger.assign(month=pd.Series(dtype=object))
    ledger["date"] = ledger["date"].dt.tz_convert(tz)
    ledger["month"] = months(ledger["date"])
    return ledger


def currencies(frame: pd.DataFrame) -> list[str]:
    """Currencies seen, the most used first."""
    return frame["currency"].value_counts().index.tolist() if not frame.empty else []


def category_slots(ledger: pd.DataFrame) -> dict[str, int]:
    """A color slot for each of the biggest spending categories. Ranked over all time, not
    the period shown, so a category keeps its color as filters change."""
    if ledger.empty:
        return {}
    spent = ledger[ledger["counted"] & (ledger["amount"] > 0)].groupby("category")["amount"].sum()
    top = spent.sort_index().sort_values(ascending=False, kind="stable").index[:SLOTS]
    return {category: slot for slot, category in enumerate(top)}


def group_of(category: str, slots: dict[str, int]) -> str:
    return category if category in slots else EVERYTHING_ELSE


def tidy(name) -> str:
    """A merchant or payee as written in an alert, without the shouting: "DOT LAHORE" -> "Dot Lahore"."""
    name = str(name or "").strip()
    return name.title() if name.isupper() else name


def day_label(day: dt.date, today: dt.date) -> str:
    if day == today:
        return "Today"
    if day == today - dt.timedelta(days=1):
        return "Yesterday"
    return f"{day:%A} {day.day} {day:%b}" + ("" if day.year == today.year else f" {day.year}")


def clock(when: dt.datetime) -> str:
    return f"{when:%I:%M %p}".lstrip("0").lower()


def short_date(day: dt.date, today: dt.date) -> str:
    return f"{day.day} {day:%b}" + ("" if day.year == today.year else f" {day.year}")


def payment_rows(rows: pd.DataFrame, today: dt.date, by_day: bool = True) -> list[dict]:
    """Ledger rows (newest first, local dates) as list rows. `by_day` lists them under day
    headers with the time on each; otherwise each row carries its date."""
    result = []
    for row in rows.itertuples():
        day = row.date.date()
        money_in = row.amount < 0
        when = clock(row.date) if by_day else short_date(day, today)
        sub = f"{row.category} · " + (row.paid_with if row.kind == "Order" and row.paid_with else row.source)
        if row.note:
            sub += f" · {row.note}"
        result.append({
            "id": row.item,
            "title": tidy(row.description) or row.source,
            "sub": sub,
            "amount": ("+" if money_in else "") + money(abs(row.amount), row.currency),
            "meta": when if row.counted else f"{when} · not counted",
            "money_in": bool(money_in),
            "category": row.category,
            "day": day.isoformat(),
            "day_label": day_label(day, today),
        })
    return result


def source_name(key: str, store: OrderStore) -> str:
    """Display name for a delivery service key, 'acct:<institution>' or 'stmt:<institution>'."""
    if key in PROVIDERS:
        return PROVIDERS[key].name
    names = {i.key: i.name for i in store.institutions()}
    if key.startswith(SOURCE_PREFIX):
        return names.get(key[len(SOURCE_PREFIX):], key[len(SOURCE_PREFIX):])
    if key.startswith(STATEMENT_PREFIX):
        return names.get(key[len(STATEMENT_PREFIX):], key[len(STATEMENT_PREFIX):]) + " statements"
    return key


def plural(count: int, word: str, many: str | None = None) -> str:
    return f"{count} {word if count == 1 else many or word + 's'}"


def rounded(value: float, step: int = 500) -> float:
    return float(round(value / step) * step)
