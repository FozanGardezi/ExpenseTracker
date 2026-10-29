import datetime as dt

import pandas as pd

from order_tracker.importers import guess_mapping, orders_from_csv
from order_tracker.models import Email, Order
from order_tracker.storage import OrderStore
from order_tracker.sync import sync_gmail
from order_tracker.parsers import PROVIDERS

WHEN = dt.datetime(2026, 5, 1, 9, 0, tzinfo=dt.UTC)


def make_order(key: str = "careem:B-1", amount: float = 500.0) -> Order:
    return Order("careem", key, WHEN, amount, "PKR", "Careem Ride", "Ride")


def test_store_deduplicates_by_order_key(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    assert store.add_order(make_order()) is True
    assert store.add_order(make_order()) is False
    df = store.orders_frame()
    assert len(df) == 1
    assert df.loc[0, "order_date"] == pd.Timestamp(WHEN)


def test_forget_gmail_data_keeps_csv_orders(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    store.add_order(make_order("careem:B-1"))
    csv_order = make_order("careem:csv:abc", amount=320.0)
    csv_order.source = "csv"
    store.add_order(csv_order)
    store.mark_processed(Email("m1", "x", "s", WHEN), "careem", "order", "")
    store.forget_gmail_data(["careem"])
    assert list(store.orders_frame()["order_key"]) == ["careem:csv:abc"]
    assert store.processed_ids("careem") == set()


class FakeGmail:
    def __init__(self, emails: dict[str, Email]):
        self.emails = emails
        self.fetched: list[str] = []

    def list_message_ids(self, query: str) -> list[str]:
        return list(self.emails)

    def get_email(self, message_id: str, attachments: bool = False) -> Email:
        self.fetched.append(message_id)
        return self.emails[message_id]


def test_sync_only_downloads_new_messages(tmp_path):
    store = OrderStore(tmp_path / "orders.db")
    gmail = FakeGmail({
        "a": Email("a", "Careem", "Your trip receipt", WHEN, ["Booking ID B-77\nTotal PKR 300"]),
        "b": Email("b", "Careem", "Ride with us again", WHEN, ["Rides from Rs. 99!"]),
    })
    stats = sync_gmail(gmail, store, [PROVIDERS["careem"]], days=30)["careem"]
    assert (stats.added, stats.skipped) == (1, 1)
    assert store.last_sync() is not None

    gmail.emails["c"] = Email("c", "Careem", "Your trip receipt", WHEN, ["Booking ID B-78\nTotal PKR 450"])
    gmail.fetched.clear()
    stats = sync_gmail(gmail, store, [PROVIDERS["careem"]], days=30)["careem"]
    assert gmail.fetched == ["c"]
    assert stats.added == 1
    assert len(store.orders_frame()) == 2
    assert list(store.skipped_frame()["subject"]) == ["Ride with us again"]


def test_guess_mapping_matches_whole_words():
    columns = ["Ride Type", "Pickup Time", "Booking_ID", "Total Fare (PKR)", "Paid By"]
    mapping = guess_mapping(columns)
    assert mapping["date"] == "Pickup Time"
    assert mapping["amount"] == "Total Fare (PKR)"
    assert mapping["reference"] == "Booking_ID"


def test_orders_from_csv(tmp_path):
    df = pd.DataFrame({
        "Date": ["31/01/2026 18:20", "02/02/2026 09:05", "not a date"],
        "Fare": ["PKR 1,250", "480", "100"],
        "Car Type": ["Go", "Bike", "Go"],
        "Booking ID": ["B-1", None, "B-3"],
    })
    mapping = guess_mapping(list(df.columns))
    orders, bad_rows = orders_from_csv(df, "careem", mapping, "PKR", dayfirst=True)
    assert bad_rows == 1
    assert [o.amount for o in orders] == [1250.0, 480.0]
    assert orders[0].order_key == "careem:B-1"
    assert orders[1].order_key.startswith("careem:csv:")
    assert orders[0].order_date.astimezone().date() == dt.date(2026, 1, 31)
    assert orders[0].merchant == "Go"
