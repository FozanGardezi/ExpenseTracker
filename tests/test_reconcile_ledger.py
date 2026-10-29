"""Linking payments to orders, internal transfers, and the combined ledger."""

import datetime as dt

from order_tracker.institutions import InstitutionSource, source_key
from order_tracker.ledger import NOT_SEEN, build_ledger
from order_tracker.models import Email, Institution, Order, Transaction
from order_tracker.reconcile import reconcile
from order_tracker.storage import OrderStore
from order_tracker.sync import sync_gmail

T0 = dt.datetime(2026, 9, 1, 15, 0, tzinfo=dt.UTC)
MEEZAN = Institution("meezan", "Meezan Bank", "bank", ["meezan"])
JAZZCASH = Institution("jazzcash", "JazzCash", "wallet", ["jazzcash"])


def at(minutes: float) -> dt.datetime:
    return T0 + dt.timedelta(minutes=minutes)


def order(key, amount, minutes=0, provider="foodpanda", merchant="Homs"):
    return Order(provider, key, at(minutes), amount, "PKR", merchant, "Food", "gmail")


def txn(key, amount, direction="debit", minutes=0, institution="meezan", description="POS"):
    return Transaction(institution, key, at(minutes), amount, "PKR", direction, description, "Other")


def make_store(tmp_path) -> OrderStore:
    store = OrderStore(tmp_path / "orders.db")
    store.save_institution(MEEZAN)
    store.save_institution(JAZZCASH)
    return store


def row(ledger, item):
    return ledger[ledger["item"] == item].iloc[0]


def test_card_payment_for_an_order_counts_once(tmp_path):
    store = make_store(tmp_path)
    store.add_order(order("foodpanda:A1", 1884.99))
    store.add_transaction(txn("meezan:R1", 1884.99, minutes=1, description="FOODPANDA PK"))
    assert reconcile(store).matched_orders == 1

    ledger = build_ledger(store)
    assert list(ledger["item"]) == ["order:foodpanda:A1"]
    assert row(ledger, "order:foodpanda:A1")["paid_with"] == "Meezan Bank"


def test_cash_order_and_other_spending_both_count(tmp_path):
    store = make_store(tmp_path)
    store.add_order(order("indrive:msg:1", 620, provider="indrive", merchant="inDrive City"))
    store.add_transaction(txn("meezan:R2", 3000, minutes=30, description="K-ELECTRIC"))
    reconcile(store)

    ledger = build_ledger(store)
    assert row(ledger, "order:indrive:msg:1")["paid_with"] == NOT_SEEN
    assert row(ledger, "txn:meezan:R2")["amount"] == 3000
    assert ledger["amount"].sum() == 3620


def test_named_merchant_matches_further_apart(tmp_path):
    store = make_store(tmp_path)
    store.add_order(order("foodpanda:A1", 1000))
    store.add_order(order("careem:B1", 450, provider="careem"))
    # Settled 20 hours later, but the alert names the service.
    store.add_transaction(txn("meezan:R1", 1000, minutes=20 * 60, description="FOODPANDA"))
    # Same gap without a name: not linked.
    store.add_transaction(txn("meezan:R2", 450, minutes=20 * 60, description="POS 88213"))
    assert reconcile(store).matched_orders == 1
    assert len(build_ledger(store)) == 3


def test_each_order_matches_one_payment(tmp_path):
    store = make_store(tmp_path)
    store.add_order(order("foodpanda:A1", 900))
    store.add_transaction(txn("meezan:R1", 900, minutes=1, description="FOODPANDA"))
    store.add_transaction(txn("meezan:R2", 900, minutes=3, description="FOODPANDA"))
    assert reconcile(store).matched_orders == 1


def test_refund_credit_matches_refund_order(tmp_path):
    store = make_store(tmp_path)
    store.add_order(order("foodpanda:A1:refund", -500))
    store.add_transaction(txn("meezan:C1", 500, direction="credit", minutes=10, description="FOODPANDA"))
    assert reconcile(store).matched_orders == 1


def test_move_between_own_accounts_is_a_transfer(tmp_path):
    store = make_store(tmp_path)
    store.add_transaction(txn("meezan:T1", 5000, minutes=0, description="JAZZCASH"))
    store.add_transaction(txn("jazzcash:T2", 5000, direction="credit", minutes=4, institution="jazzcash",
                              description="Meezan Bank"))
    store.add_transaction(txn("meezan:T3", 5000, minutes=5 * 60, description="Ali"))  # too late to pair
    assert reconcile(store).transfers == 1

    ledger = build_ledger(store)
    transfers = ledger[ledger["transfer"]]
    assert set(transfers["item"]) == {"txn:meezan:T1", "txn:jazzcash:T2"}
    assert set(transfers["category"]) == {"Transfers"}
    assert ledger.loc[~ledger["transfer"], "amount"].sum() == 5000


def test_category_override(tmp_path):
    store = make_store(tmp_path)
    store.add_transaction(txn("meezan:R1", 750, description="ABC TRADERS"))
    store.set_category("txn:meezan:R1", "Shopping")
    assert row(build_ledger(store), "txn:meezan:R1")["category"] == "Shopping"


def test_empty_ledger(tmp_path):
    assert build_ledger(make_store(tmp_path)).empty


def test_institutions_round_trip_and_delete(tmp_path):
    store = make_store(tmp_path)
    custom = Institution("silk", "Silkbank", "bank", ["alerts@silkbank.com.pk", "silk bank"],
                         ["Transaction Alert"], "PKR", enabled=False)
    store.save_institution(custom)
    assert store.institutions()[-1] == custom  # sorted by name: JazzCash, Meezan Bank, Silkbank
    assert InstitutionSource(custom).gmail_query == (
        'from:(alerts@silkbank.com.pk OR "silk bank") subject:("Transaction Alert")'
    )

    store.add_transaction(txn("meezan:R1", 100))
    store.mark_processed(Email("m1", "x", "s", T0), source_key("meezan"), "added", "")
    store.delete_institution("meezan")
    assert [i.key for i in store.institutions()] == ["jazzcash", "silk"]
    assert store.transactions_frame().empty
    assert store.processed_ids(source_key("meezan")) == set()


class FakeGmail:
    def __init__(self, by_query: dict[str, list[Email]]):
        self.by_query = by_query
        self.emails = {e.message_id: e for emails in by_query.values() for e in emails}

    def list_message_ids(self, query: str) -> list[str]:
        return [e.message_id for key, emails in self.by_query.items() if query.startswith(key) for e in emails]

    def get_email(self, message_id: str, attachments: bool = False) -> Email:
        return self.emails[message_id]


def test_sync_reads_bank_alerts_and_links_them(tmp_path):
    from order_tracker.parsers import PROVIDERS

    store = make_store(tmp_path)
    gmail = FakeGmail({
        "from:(foodpanda)": [Email("f1", "foodpanda", "Your order", at(0),
                                   ["Order number: x7kq-p3m9\nPartner:\nName: Homs\nTotal PKR 1,884.99"])],
        "from:(meezan)": [
            Email("b1", "Meezan Bank", "Transaction Alert", at(2),
                  ["PKR 1,884.99 debited from A/C ****1234 at FOODPANDA PK on 01-Sep. Ref No. 6244123"]),
            Email("b2", "Meezan Bank", "Transaction Alert", at(90),
                  ["PKR 3,200.00 debited from A/C ****1234 at K-ELECTRIC. Ref No. 6244999"]),
            Email("b3", "Meezan Bank", "Your OTP", at(91), ["Your OTP is 1234"]),
        ],
    })
    results = sync_gmail(gmail, store, [PROVIDERS["foodpanda"], InstitutionSource(MEEZAN)], days=30)

    assert results["acct:meezan"].added == 2 and results["acct:meezan"].skipped == 1
    ledger = build_ledger(store)
    assert ledger["amount"].sum() == 1884.99 + 3200
    assert row(ledger, "order:foodpanda:X7KQ-P3M9")["paid_with"] == "Meezan Bank"
    assert list(store.skipped_frame()["provider"]) == ["acct:meezan"]

    store.forget_gmail_data(["acct:meezan"])
    assert store.transactions_frame().empty
    assert len(store.orders_frame()) == 1


# --- transfers and spending ---

def test_transfers_are_not_spending_unless_within_the_limit_or_categorised(tmp_path):
    from order_tracker.ledger import set_transfer_rule

    store = make_store(tmp_path)
    store.add_transaction(Transaction("meezan", "meezan:T1", at(0), 800, "PKR", "debit", "AHMED", "Transfers"))
    store.add_transaction(Transaction("meezan", "meezan:T2", at(5), 25000, "PKR", "debit", "ALI", "Transfers"))
    store.add_transaction(Transaction("meezan", "meezan:B1", at(9), 3000, "PKR", "debit", "K-ELECTRIC", "Bills & utilities"))

    def counted() -> dict[str, bool]:
        return dict(zip(build_ledger(store)["item"], build_ledger(store)["counted"]))

    assert counted() == {"txn:meezan:T1": False, "txn:meezan:T2": False, "txn:meezan:B1": True}

    set_transfer_rule(store, 1000, "PKR")  # small transfers count
    assert counted()["txn:meezan:T1"] and not counted()["txn:meezan:T2"]

    store.set_category("txn:meezan:T2", "Rent")  # a categorised transfer always counts
    assert counted()["txn:meezan:T2"]
    ledger = build_ledger(store).set_index("item")
    assert ledger.loc["txn:meezan:T2", "auto_category"] == "Transfers"


def test_moves_between_own_accounts_never_count(tmp_path):
    from order_tracker.ledger import set_transfer_rule

    store = make_store(tmp_path)
    set_transfer_rule(store, 100000, "PKR")
    store.add_transaction(txn("meezan:T1", 5000, minutes=0, description="JAZZCASH"))
    store.add_transaction(txn("jazzcash:T2", 5000, direction="credit", minutes=4, institution="jazzcash"))
    reconcile(store)
    assert not build_ledger(store)["counted"].any()


def test_clicked_month():
    from types import SimpleNamespace

    from views.common import clicked_month

    assert clicked_month(None) is None
    assert clicked_month(SimpleNamespace(selection=SimpleNamespace(points=[]))) is None
    event = SimpleNamespace(selection=SimpleNamespace(points=[{"x": "2026-09-01", "y": 100}]))
    assert str(clicked_month(event).date()) == "2026-09-01"
