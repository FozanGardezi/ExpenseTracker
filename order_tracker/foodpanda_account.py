"""Order history straight from a customer's foodpanda account.

foodpanda's website fills its "Orders" page from an order-history endpoint on
fd-api.com, authorized by the customer's login token (the `token` cookie on
foodpanda.pk). This module calls the same endpoint with a token the user
pastes in. It is not a public API: foodpanda can change or block it without
notice. The request and response shapes follow two open-source tools that use
it (asdf93074/foodpanda-total and uWayLu/FoodpandaOrderHistoryTool).

Unlike Gmail receipts, this returns every order on the account, including ones
whose emails were deleted, with the restaurant name and order code.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from .models import Order

COUNTRIES = {
    "PK": {"name": "Pakistan", "host": "pk.fd-api.com", "currency": "PKR", "tz": "Asia/Karachi", "site": "foodpanda.pk"},
    "BD": {"name": "Bangladesh", "host": "bd.fd-api.com", "currency": "BDT", "tz": "Asia/Dhaka", "site": "foodpanda.com.bd"},
}
PAGE_SIZE = 20
MAX_PAGES = 250  # 5,000 orders; a guard against an endpoint that never stops paging


class FoodpandaAuthError(Exception):
    """The token was rejected (expired, mistyped, or for another country)."""


class FoodpandaAPIError(Exception):
    """The endpoint failed or answered with something unexpected."""


def clean_token(raw: str) -> str:
    token = raw.strip().strip('"').strip("'")
    return token[len("Bearer "):].strip() if token.lower().startswith("bearer ") else token


def fetch_order_history(token: str, country: str = "PK", session=None) -> list[dict]:
    """Return the raw order items for the account, newest first."""
    session = session or requests.Session()
    url = f"https://{COUNTRIES[country]['host']}/api/v5/orders/order_history"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {clean_token(token)}",
        "X-FP-API-Key": "volo",  # the client id foodpanda's own website sends
    }
    items: list[dict] = []
    for page in range(MAX_PAGES):
        params = {
            "include": "order_products,order_details",
            "language_id": 1,
            "offset": page * PAGE_SIZE,
            "limit": PAGE_SIZE,
        }
        try:
            response = session.get(url, params=params, headers=headers, timeout=30)
        except requests.RequestException as exc:
            raise FoodpandaAPIError(f"Could not reach foodpanda: {exc}") from exc
        if response.status_code in (401, 403):
            raise FoodpandaAuthError(
                f"foodpanda refused the token (HTTP {response.status_code}). It may have expired: "
                "log in again on the website and copy a fresh one."
            )
        if not response.ok:
            raise FoodpandaAPIError(f"foodpanda returned HTTP {response.status_code}.")
        try:
            batch = response.json()["data"]["items"]
        except (ValueError, KeyError, TypeError) as exc:
            raise FoodpandaAPIError("foodpanda's response was not in the expected format.") from exc
        items.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
    return items


def _ordered_at(item: dict, default_tz: str) -> dt.datetime:
    raw = item["ordered_at"]
    value = raw.get("date") if isinstance(raw, dict) else raw
    tz_name = (raw.get("timezone") if isinstance(raw, dict) else None) or default_tz
    when = pd.Timestamp(value)
    if when.tzinfo is None:
        when = when.tz_localize(ZoneInfo(tz_name))
    return when.to_pydatetime().astimezone(dt.UTC)


def orders_from_history(items: list[dict], country: str = "PK") -> tuple[list[Order], int]:
    """Convert raw items to orders. Returns (orders, number of declined or unreadable items skipped)."""
    info = COUNTRIES[country]
    orders: list[Order] = []
    skipped = 0
    for item in items:
        try:
            if item.get("decline_reason"):
                raise ValueError("declined")
            code = str(item["order_code"]).strip().upper()
            amount = float(item["total_value"])
            when = _ordered_at(item, info["tz"])
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        merchant = ((item.get("vendor") or {}).get("name") or "pandamart").strip()
        category = "Groceries" if "pandamart" in merchant.lower() else "Food"
        orders.append(Order(
            provider="foodpanda",
            order_key=f"foodpanda:{code}",  # same key a receipt email with this order code gets
            order_date=when,
            amount=amount,
            currency=info["currency"],
            merchant=merchant,
            category=category,
            source="account",
        ))
    return orders, skipped
