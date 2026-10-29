"""One list of money in and out, combining orders and bank/wallet transactions.

Each purchase appears once:
- a delivery order paid by card or wallet shows as the order (it has the
  restaurant or ride details), with "Paid with" naming the bank or wallet;
- an order with no matching transaction was paid in cash or from an account
  that isn't tracked, and still counts;
- every other transaction appears as itself, including the ones the user
  added (cash, or a pasted bank message).

`amount` is positive for money out and negative for money in. `annotate`
then decides, the same way on every page:
- `category`: the app's guess (`auto_category`), then the user's rules, then
  the user's choice for that one row;
- `spent_for`: who money out was for ("Mine", "Home", ...): the user's choice
  for the row, else a rule, else the first of the user's labels;
- `counted`, whether a row counts towards spending and income: moves between
  your own accounts (`transfer`) never count; money sent by transfer (category
  "Transfers") might not be spending at all, so it only counts when it's within
  the transfer limit the user set (0 by default), or once it has a real
  category. Ticking or unticking "In spending" on a row overrides both.
"""

import pandas as pd

from .categories import ALL_CATEGORIES, categorize
from .parsers import PROVIDERS
from .rules import apply_rules, split_words
from .storage import CASH, OrderStore

TRANSFERS = "Transfers"
COLUMNS = [
    "item", "date", "description", "category", "auto_category", "amount", "currency",
    "source", "paid_with", "kind", "transfer", "counted", "spent_for", "note", "details", "came_from",
]
NOT_SEEN = "Cash / not tracked"
OTHER_ACCOUNT = "other"  # a pasted message from an account the user doesn't track
ACCOUNT_NAMES = {CASH: "Cash", OTHER_ACCOUNT: "Other account"}
# Where each row was found, by the record's source.
TXN_ORIGINS = {"gmail": "Email alert", "statement": "Monthly statement", "manual": "Added by you",
               "message": "Pasted message"}
ORDER_ORIGINS = {"gmail": "Receipt email", "csv": "Imported file", "account": "Delivery app account"}
ADDED_BY_YOU = ("Added by you", "Pasted message")
DEFAULT_SPEND_FOR = "Mine, Home"


def spend_for_labels(store: OrderStore) -> list[str]:
    """Who spending can be for; the first is used when nothing says otherwise."""
    return split_words(store.setting("spend_for", DEFAULT_SPEND_FOR)) or split_words(DEFAULT_SPEND_FOR)


def set_spend_for_labels(store: OrderStore, labels: list[str]) -> None:
    store.set_setting("spend_for", ", ".join(labels))


def my_categories(store: OrderStore) -> list[str]:
    """Categories the user added to the built-in ones, e.g. "Going out"."""
    return split_words(store.setting("my_categories", ""))


def set_my_categories(store: OrderStore, categories: list[str]) -> None:
    store.set_setting("my_categories", ", ".join(categories))


def category_options(store: OrderStore, *seen: str) -> list[str]:
    """Every category to offer in a picker: built-in, the user's own, and any already in use."""
    return sorted(set(ALL_CATEGORIES) | set(my_categories(store)) | {c for c in seen if isinstance(c, str) and c})


def transfer_rule(store: OrderStore) -> tuple[float, str]:
    """(limit, currency): transfers up to the limit, in that currency, count as spending."""
    return float(store.setting("transfer_limit", "0")), store.setting("transfer_limit_currency", "PKR")


def set_transfer_rule(store: OrderStore, limit: float, currency: str) -> None:
    store.set_setting("transfer_limit", str(limit))
    store.set_setting("transfer_limit_currency", currency)


def uncounted_transfers(category: pd.Series, money_out: pd.Series, currency: pd.Series,
                        limit: float, limit_currency: str) -> pd.Series:
    """Money sent by transfer that isn't counted as spending: over the limit and not categorised."""
    within = (currency == limit_currency) & (money_out <= limit)
    return (category == TRANSFERS) & (money_out > 0) & ~within


def build_ledger(store: OrderStore) -> pd.DataFrame:
    orders = store.orders_frame()
    txns = store.transactions_frame()
    institutions = {i.key: i for i in store.institutions()}

    def account_name(key: str) -> str:
        return institutions[key].name if key in institutions else ACCOUNT_NAMES.get(key, key)

    matched = txns.dropna(subset=["matched_order"])
    paid_with = dict(zip(matched["matched_order"], matched["institution"].map(account_name)))

    order_rows = pd.DataFrame({
        "item": "order:" + orders["order_key"],
        "date": orders["order_date"],
        "description": orders["merchant"],
        "category": orders["category"],
        "amount": orders["amount"],
        "currency": orders["currency"],
        "source": orders["provider"].map(lambda p: f"{PROVIDERS[p].name} order" if p in PROVIDERS else p),
        "paid_with": orders["order_key"].map(paid_with).fillna(NOT_SEEN),
        "kind": "Order",
        "transfer": False,
        "details": orders["subject"],
        "came_from": orders["source"].map(ORDER_ORIGINS).fillna("Receipt email"),
    })

    own = txns[txns["matched_order"].isna()]
    txn_rows = pd.DataFrame({
        "item": "txn:" + own["txn_key"],
        "date": own["txn_date"],
        "description": own["description"],
        "category": own["category"],
        "amount": own["amount"].where(own["direction"] == "debit", -own["amount"]),
        "currency": own["currency"],
        "source": own["institution"].map(account_name),
        "paid_with": "",
        "kind": own["institution"].map(
            lambda k: institutions[k].kind.title() if k in institutions else "Cash" if k == CASH else "Account"
        ),
        "transfer": own["transfer_id"].notna(),
        "details": own["subject"],
        "came_from": own["source"].map(TXN_ORIGINS).fillna("Email alert"),
    })

    frames = [frame for frame in (order_rows, txn_rows) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=COLUMNS)
    ledger = annotate(pd.concat(frames, ignore_index=True), store)
    return ledger[COLUMNS].sort_values("date", ascending=False, ignore_index=True)


def annotate(frame: pd.DataFrame, store: OrderStore) -> pd.DataFrame:
    """Add auto_category, category, spent_for, note and counted to rows with item,
    description, category, amount (+ out, - in), currency and transfer."""
    frame = frame.copy()
    frame["transfer"] = frame["transfer"].astype(bool)
    frame.loc[frame["transfer"], "category"] = TRANSFERS
    money_out = frame["amount"] > 0
    spending = money_out & ~frame["transfer"]
    # Rows read before the app learned a merchant get another try.
    unknown = spending & (frame["category"] == "Other")
    frame.loc[unknown, "category"] = frame.loc[unknown, "description"].fillna("").map(lambda d: categorize(d, "debit"))
    frame["auto_category"] = frame["category"]
    rules = store.rules()
    by_rule = apply_rules(rules, "category", frame["description"], frame["category"], frame["amount"], spending)
    frame["category"] = by_rule.fillna(frame["category"])
    frame["category"] = frame["item"].map(store.category_overrides()).fillna(frame["category"])

    details = store.item_details()
    chosen = frame["item"].map(details["spent_for"].dropna())
    # "Groceries are for Home" also covers rows whose category the user picked by hand.
    for_rule = apply_rules(rules, "spent_for", frame["description"], frame["category"], frame["amount"], spending)
    frame["spent_for"] = chosen.fillna(for_rule).fillna(spend_for_labels(store)[0]).where(money_out, "")
    frame["note"] = frame["item"].map(details["note"].dropna()).fillna("")

    limit, limit_currency = transfer_rule(store)
    automatic = ~frame["transfer"] & ~uncounted_transfers(
        frame["category"], frame["amount"], frame["currency"], limit, limit_currency
    )
    ticked = frame["item"].map(details["counted"].dropna().astype(bool))
    frame["counted"] = ticked.where(ticked.notna(), automatic).astype(bool)
    return frame
