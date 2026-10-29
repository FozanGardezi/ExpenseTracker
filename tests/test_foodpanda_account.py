"""foodpanda account import, against fake responses shaped like the order-history endpoint."""

import datetime as dt

import pytest

from order_tracker.foodpanda_account import (
    PAGE_SIZE, FoodpandaAPIError, FoodpandaAuthError, clean_token, fetch_order_history,
    orders_from_history,
)
from order_tracker.models import Order
from order_tracker.storage import OrderStore


class FakeResponse:
    def __init__(self, status: int, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params, headers, timeout):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def item(code: str, total: float, when: str = "2026-09-01T20:15:00+05:00", vendor="Homs", **extra):
    return {"order_code": code, "total_value": total, "ordered_at": {"date": when},
            "vendor": {"name": vendor}, **extra}


def page(items):
    return FakeResponse(200, {"data": {"items": items}})


def test_fetch_follows_pages_until_a_short_page():
    first = [item(f"a{i}-0001", 100.0) for i in range(PAGE_SIZE)]
    session = FakeSession([page(first), page([item("b0-0002", 250.0)])])
    items = fetch_order_history("Bearer abc.def.ghi", "PK", session)

    assert len(items) == PAGE_SIZE + 1
    (url, params, headers), (_, second_params, _) = session.calls
    assert url == "https://pk.fd-api.com/api/v5/orders/order_history"
    assert headers["Authorization"] == "Bearer abc.def.ghi"
    assert headers["X-FP-API-Key"] == "volo"
    assert (params["offset"], second_params["offset"]) == (0, PAGE_SIZE)


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_token(status):
    with pytest.raises(FoodpandaAuthError):
        fetch_order_history("expired", "PK", FakeSession([FakeResponse(status)]))


def test_unexpected_response():
    with pytest.raises(FoodpandaAPIError):
        fetch_order_history("t", "PK", FakeSession([FakeResponse(200, {"error": "nope"})]))
    with pytest.raises(FoodpandaAPIError):
        fetch_order_history("t", "PK", FakeSession([FakeResponse(500)]))


def test_clean_token():
    assert clean_token('  "Bearer abc.def"  ') == "abc.def"
    assert clean_token("abc.def\n") == "abc.def"


def test_orders_from_history():
    items = [
        item("x7kq-p3m9", 1884.99),
        item("m1ab-0001", 2450.0, vendor="pandamart - Gulberg"),
        item("d3cl-0002", 900.0, decline_reason="restaurant closed"),
        item("n0tz-0003", 500.0, when="2026-09-02 13:00:00"),  # no offset: Pakistan time
        {"order_code": "brok-0004"},  # missing fields
    ]
    orders, skipped = orders_from_history(items, "PK")

    assert skipped == 2
    assert [o.order_key for o in orders] == ["foodpanda:X7KQ-P3M9", "foodpanda:M1AB-0001", "foodpanda:N0TZ-0003"]
    assert orders[0].order_date == dt.datetime(2026, 9, 1, 15, 15, tzinfo=dt.UTC)
    assert (orders[0].merchant, orders[0].category, orders[0].currency) == ("Homs", "Food", "PKR")
    assert orders[1].category == "Groceries"
    assert orders[2].order_date == dt.datetime(2026, 9, 2, 8, 0, tzinfo=dt.UTC)
    assert all(o.source == "account" for o in orders)


# --- the same order arriving from Gmail and from the account counts once ---

WHEN = dt.datetime(2026, 9, 1, 15, 15, tzinfo=dt.UTC)


def order(key, source, amount=1884.99, minutes=0):
    return Order("foodpanda", key, WHEN + dt.timedelta(minutes=minutes), amount, "PKR", "Homs", "Food", source)


def test_account_order_matches_receipt_without_order_number(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    assert store.add_order(order("foodpanda:msg:18c2", "gmail", minutes=2))
    assert not store.add_order(order("foodpanda:X7KQ-P3M9", "account"))
    assert len(store.orders_frame()) == 1


def test_receipt_without_order_number_matches_account_order(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    assert store.add_order(order("foodpanda:X7KQ-P3M9", "account"))
    assert not store.add_order(order("foodpanda:msg:18c2", "gmail", minutes=-30))


def test_same_order_number_dedupes_across_sources(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    assert store.add_order(order("foodpanda:X7KQ-P3M9", "gmail"))
    assert not store.add_order(order("foodpanda:X7KQ-P3M9", "account"))


@pytest.mark.parametrize(
    "first, second",
    [
        # Same source: two identical orders really were placed.
        (order("foodpanda:msg:1", "gmail"), order("foodpanda:msg:2", "gmail")),
        # Different amount.
        (order("foodpanda:msg:1", "gmail"), order("foodpanda:A1B2-0009", "account", amount=950)),
        # Four hours apart.
        (order("foodpanda:msg:1", "gmail"), order("foodpanda:A1B2-0009", "account", minutes=240)),
        # Both carry order numbers, and they differ.
        (order("foodpanda:X7KQ-P3M9", "gmail"), order("foodpanda:A1B2-0009", "account")),
    ],
)
def test_distinct_orders_are_kept(tmp_path, first, second):
    store = OrderStore(tmp_path / "orders.db")
    assert store.add_order(first)
    assert store.add_order(second)
