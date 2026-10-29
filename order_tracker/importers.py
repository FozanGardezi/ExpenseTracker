"""CSV import, for history exported from a service (e.g. careem.com ride history)
or kept by hand. Column names vary, so columns are guessed and the app lets the
user correct the mapping before importing."""

import datetime as dt
import hashlib
import re

import pandas as pd

from .models import Order
from .parsers import PROVIDERS
from .parsers.base import find_money, normalize_currency, parse_number

# Checked in order; the first hint found in a column name wins.
COLUMN_HINTS = {
    "date": ("date", "time", "created", "booked", "pickup", "pick up"),
    "amount": ("total", "amount", "fare", "price", "cost", "paid", "charge"),
    "merchant": ("restaurant", "merchant", "store", "vendor", "service", "product", "vehicle", "car type", "description"),
    "reference": ("order id", "booking id", "trip id", "ride id", "order no", "order number", "booking", "reference", "id"),
    "currency": ("currency",),
}

DEFAULT_CATEGORY = {
    "foodpanda": "Food",
    "careem": "Ride",
    "indrive": "Ride",
    "kravemart": "Groceries",
}

LOCAL_TZ = dt.datetime.now().astimezone().tzinfo


def _words(column: str) -> str:
    """'Booking_ID' -> 'booking id', so hints match whole words only ('id' must not hit 'ride')."""
    return " " + re.sub(r"[^a-z0-9]+", " ", column.lower()).strip() + " "


def guess_mapping(columns: list[str]) -> dict[str, str | None]:
    mapping: dict[str, str | None] = {}
    taken: set[str] = set()
    for field, hints in COLUMN_HINTS.items():
        mapping[field] = None
        for hint in hints:
            match = next(
                (c for c in columns if c not in taken and f" {hint} " in _words(c)), None
            )
            if match:
                mapping[field] = match
                taken.add(match)
                break
    return mapping


def _amount_and_currency(value, default_currency: str) -> tuple[float | None, str]:
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value), default_currency
    text = str(value)
    money = find_money(text)
    if money:
        return money
    try:
        return parse_number(text.strip()), default_currency
    except ValueError:
        return None, default_currency


def orders_from_csv(
    df: pd.DataFrame,
    provider_key: str,
    mapping: dict[str, str | None],
    default_currency: str,
    dayfirst: bool = True,
) -> tuple[list[Order], int]:
    """Convert CSV rows into orders. Returns (orders, number of rows that could not be read)."""
    provider = PROVIDERS[provider_key]
    dates = pd.to_datetime(df[mapping["date"]], errors="coerce", dayfirst=dayfirst, format="mixed")
    orders: list[Order] = []
    bad_rows = 0

    for idx, row in df.iterrows():
        when = dates.loc[idx]
        amount, currency = _amount_and_currency(row[mapping["amount"]], default_currency)
        if pd.isna(when) or amount is None:
            bad_rows += 1
            continue
        when = when.tz_localize(LOCAL_TZ) if when.tzinfo is None else when
        when = when.to_pydatetime().astimezone(dt.UTC)

        if mapping.get("currency") and pd.notna(row[mapping["currency"]]):
            currency = normalize_currency(str(row[mapping["currency"]]))
        merchant = provider.name
        if mapping.get("merchant") and pd.notna(row[mapping["merchant"]]):
            merchant = str(row[mapping["merchant"]]).strip()

        reference = row[mapping["reference"]] if mapping.get("reference") else None
        if reference is not None and pd.notna(reference) and str(reference).strip():
            order_key = f"{provider_key}:{str(reference).strip().upper()}"
        else:
            fingerprint = f"{when.isoformat()}|{amount}|{merchant}"
            order_key = f"{provider_key}:csv:{hashlib.sha1(fingerprint.encode()).hexdigest()[:16]}"

        orders.append(Order(
            provider=provider_key,
            order_key=order_key,
            order_date=when,
            amount=amount,
            currency=currency,
            merchant=merchant,
            category=DEFAULT_CATEGORY[provider_key],
            source="csv",
        ))
    return orders, bad_rows
