"""Link transactions to orders and to each other so nothing is counted twice.

- A card or wallet payment for a delivery order shows up twice: as the order
  (from the service's receipt) and as a debit (from the bank's alert). They
  are linked when the amounts agree and the times are close, and the pair
  counts once.
- Moving money between two of your own tracked accounts (bank to JazzCash, say)
  shows up as a debit in one and a credit in the other. Both legs are marked as
  an internal transfer and left out of spending and income. Expenses the user
  typed in are never one of the legs.

Statement rows carry a date but no time, so their windows are measured in days.

Links are recomputed from scratch after every sync, so they follow new data.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd

from .storage import OrderStore

AMOUNT_TOLERANCE = 1.0  # rounding differences between receipt and alert
TRANSFER_WINDOW = dt.timedelta(hours=2)
ORDER_WINDOW = dt.timedelta(hours=2)  # when the alert doesn't name the service
NAMED_ORDER_WINDOW = dt.timedelta(hours=48)  # when it does ("FOODPANDA" in the alert)
# Statement rows: midday of the listed date, which may be the posting date.
STATEMENT_TRANSFER_WINDOW = dt.timedelta(days=3)
STATEMENT_ORDER_WINDOW = dt.timedelta(days=1)
STATEMENT_NAMED_ORDER_WINDOW = dt.timedelta(days=3)

SERVICE_WORDS = {
    "foodpanda": ("foodpanda", "food panda", "pandamart", "delivery hero"),
    "careem": ("careem",),
    "indrive": ("indrive", "indriver", "suol"),
    "kravemart": ("krave",),
}


@dataclass
class ReconcileStats:
    matched_orders: int
    transfers: int


def reconcile(store: OrderStore) -> ReconcileStats:
    txns = store.transactions_frame()
    transfers = find_transfers(txns[txns["source"] != "manual"])
    matches = match_orders(txns[~txns["txn_key"].isin(set(transfers))], store.orders_frame())
    store.set_reconciliation(matches, transfers)
    return ReconcileStats(len(matches), len(transfers) // 2)


def find_transfers(txns: pd.DataFrame) -> dict[str, str]:
    """Pair a debit in one account with a same-amount credit in another, close in time."""
    result: dict[str, str] = {}
    credits = txns[txns["direction"] == "credit"]
    from_statement = credits["source"] == "statement"
    for debit in txns[txns["direction"] == "debit"].sort_values("txn_date").itertuples():
        gap = (credits["txn_date"] - debit.txn_date).abs()
        window = (from_statement | (debit.source == "statement")).map(
            {True: STATEMENT_TRANSFER_WINDOW, False: TRANSFER_WINDOW}
        )
        pool = credits[
            (credits["institution"] != debit.institution)
            & (credits["currency"] == debit.currency)
            & ((credits["amount"] - debit.amount).abs() < 0.005)
            & (gap <= window)
            & ~credits["txn_key"].isin(set(result))
        ]
        if pool.empty:
            continue
        credit_key = pool.loc[gap[pool.index].idxmin(), "txn_key"]
        transfer_id = f"transfer:{debit.txn_key}"
        result[debit.txn_key] = transfer_id
        result[credit_key] = transfer_id
    return result


def match_orders(txns: pd.DataFrame, orders: pd.DataFrame) -> dict[str, str]:
    """Link each transaction to at most one order, and each order to at most one transaction."""
    matches: dict[str, str] = {}
    if txns.empty or orders.empty:
        return matches
    used: set[str] = set()
    for txn in txns.sort_values("txn_date").itertuples():
        # Orders are positive for purchases and negative for refunds, like a debit/credit.
        spend = txn.amount if txn.direction == "debit" else -txn.amount
        pool = orders[
            (orders["currency"] == txn.currency)
            & ((orders["amount"] - spend).abs() <= AMOUNT_TOLERANCE)
            & ~orders["order_key"].isin(used)
        ]
        if pool.empty:
            continue
        text = f"{txn.description} {txn.subject}".lower()
        named = {p for p, words in SERVICE_WORDS.items() if any(w in text for w in words)}
        gap = (pool["order_date"] - txn.txn_date).abs()
        if txn.source == "statement":
            windows = {True: STATEMENT_NAMED_ORDER_WINDOW, False: STATEMENT_ORDER_WINDOW}
        else:
            windows = {True: NAMED_ORDER_WINDOW, False: ORDER_WINDOW}
        window = pool["provider"].isin(named).map(windows)
        pool = pool[gap <= window]
        if pool.empty:
            continue
        order_key = pool.loc[gap[pool.index].idxmin(), "order_key"]
        matches[txn.txn_key] = order_key
        used.add(order_key)
    return matches
