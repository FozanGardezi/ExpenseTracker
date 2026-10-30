"""One payment (to change or remove it), and adding an expense: typed in, or pasted from
a bank's SMS or app notification."""

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from order_tracker.alerts import find_date, parse_message
from order_tracker.categories import categorize
from order_tracker.ledger import ADDED_BY_YOU, OTHER_ACCOUNT, category_options, spend_for_labels
from order_tracker.models import Institution, Transaction
from order_tracker.money import money
from order_tracker.reconcile import reconcile
from order_tracker.storage import CASH, OrderStore

from .common import currencies, local_ledger, tidy, today_in, user_store, viewer_tz

router = APIRouter(prefix="/api")


def _accounts(store: OrderStore) -> dict[str, str]:
    return {CASH: "Cash", **{i.key: i.name for i in store.institutions()}}


def _when(row: pd.Series) -> str:
    """"23 Oct 2026 at 11:42 am"; statements give a date only."""
    day = f"{row['date'].day} {row['date']:%b %Y}"
    if row["came_from"] == "Monthly statement":
        return day
    return f"{day} at {row['date']:%I:%M}".replace(" at 0", " at ") + f" {row['date']:%p}".lower()


def _sentence(row: pd.Series) -> str:
    when = _when(row)
    name = f"**{tidy(row['description'])}**"
    if row["kind"] == "Order":
        paid = f", paid with **{row['paid_with']}**" if row["paid_with"] else ""
        return f"{row['source']} from {name}{paid} on {when}"
    if row["came_from"] == "Added by you":
        paid = "in cash" if row["kind"] == "Cash" else f"from **{row['source']}**"
        return f"{name}, paid {paid} on {when}"
    account = f"**{row['source']}**"
    if row["amount"] < 0:
        return f"Received from {name} into {account} on {when}"
    return f"Paid to {name} from {account} on {when}"


def _row(store: OrderStore, item: str, tz) -> pd.Series:
    ledger = local_ledger(store, tz)
    found = ledger[ledger["item"] == item]
    if found.empty:
        raise HTTPException(404, "This payment isn't there any more.")
    return found.iloc[0]


@router.get("/payments/{item:path}")
def payment(item: str, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """One payment, like a banking app's detail sheet."""
    row = _row(store, item, tz)
    money_out = row["amount"] > 0
    typed = row["came_from"] in ADDED_BY_YOU
    txn = store.transaction(item[4:]) if item.startswith("txn:") else None
    accounts = _accounts(store)
    if txn and txn["institution"] not in accounts:
        accounts[txn["institution"]] = row["source"]
    details = [("Came from", row["came_from"]), ("When", _when(row)),
               ("Account", row["paid_with"] if row["kind"] == "Order" else row["source"])]
    if txn and txn.get("reference"):
        details.append(("Reference", txn["reference"]))
    if row["details"] and not typed:
        details.append(("Email subject", row["details"]))
    if row["came_from"] == "Pasted message" and txn:
        details.append(("Message", txn["subject"]))
    return {
        "item": item,
        "title": tidy(row["description"]) or row["source"],
        "amount": ("-" if money_out else "+") + money(abs(row["amount"]), row["currency"]),
        "money_out": bool(money_out),
        "sentence": _sentence(row),
        "category": row["category"],
        "spent_for": row["spent_for"] or None,
        "note": row["note"],
        "counted": bool(row["counted"]),
        "transfer": bool(row["transfer"]),
        "counted_label": "Count as spending" if money_out else "Count as money in",
        "typed": {
            "amount": float(abs(row["amount"])), "description": row["description"],
            "date": row["date"].date().isoformat(), "account": txn["institution"],
        } if typed and txn else None,
        "options": {
            "categories": category_options(store, row["category"]),
            "labels": list(dict.fromkeys(spend_for_labels(store) + ([row["spent_for"]] if row["spent_for"] else []))),
            "accounts": [{"key": k, "name": v} for k, v in accounts.items()],
        },
        "details": [{"label": label, "value": str(value)} for label, value in details if value],
    }


class PaymentChange(BaseModel):
    category: str | None = None
    spent_for: str | None = None   # null: back to what the rules say
    note: str | None = None
    counted: bool | None = None
    # Only for something the user added:
    amount: float | None = None
    description: str | None = None
    date: dt.date | None = None
    account: str | None = None


@router.patch("/payments/{item:path}")
def change_payment(item: str, body: PaymentChange, store: OrderStore = Depends(user_store),
                   tz=Depends(viewer_tz)) -> dict:
    row = _row(store, item, tz)
    sent = body.model_fields_set
    typed = row["came_from"] in ADDED_BY_YOU
    edits_typed = sent & {"amount", "description", "date", "account"}
    if edits_typed and not typed:
        raise HTTPException(400, "Only expenses you added can have their amount, date or account changed.")
    if typed and edits_typed:
        txn = store.transaction(item[4:])
        amount = body.amount if "amount" in sent else txn["amount"]
        description = (body.description if "description" in sent else txn["description"]) or ""
        if not amount or not description.strip():
            raise HTTPException(400, "Enter the amount and what it was.")
        when = row["date"]
        if "date" in sent and body.date and body.date != row["date"].date():
            if body.date > today_in(tz):
                raise HTTPException(400, "That date is in the future.")
            when = dt.datetime.combine(body.date, dt.time(12), tz)
        account = body.account if "account" in sent and body.account else txn["institution"]
        store.update_typed(txn["txn_key"], when, float(amount), description.strip(), account)

    if "category" in sent and body.category and body.category != row["category"]:
        store.set_category(item, body.category)
    if "spent_for" in sent and row["amount"] > 0 and body.spent_for != row["spent_for"]:
        store.set_item_detail(item, "spent_for", body.spent_for or None)
    if "note" in sent and (body.note or "").strip() != row["note"]:
        store.set_item_detail(item, "note", (body.note or "").strip() or None)
    if "counted" in sent and body.counted is not None and body.counted != bool(row["counted"]):
        if row["transfer"]:
            raise HTTPException(400, "This moved money between your own accounts, so it isn't spending or income.")
        store.set_item_detail(item, "counted", body.counted)
    if typed and edits_typed:
        reconcile(store)
    return {"message": "Saved."}


@router.delete("/payments/{item:path}")
def remove_payment(item: str, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Remove an expense the user added (typed in or pasted)."""
    row = _row(store, item, tz)
    if row["came_from"] not in ADDED_BY_YOU:
        raise HTTPException(400, "Only expenses you added can be removed.")
    store.delete_typed(item[4:])
    reconcile(store)
    return {"message": f"Removed {tidy(row['description'])}."}


# --- adding an expense ---

def _reader(store: OrderStore, account: str, currency: str) -> Institution:
    institutions = {i.key: i for i in store.institutions()}
    return institutions.get(account) or Institution(OTHER_ACCOUNT, "Another account", "bank", [], currency=currency)


def _default_currency(store: OrderStore) -> str:
    seen = currencies(store.transactions_frame())
    return seen[0] if seen else "PKR"


def _parse(store: OrderStore, text: str, account: str, tz) -> tuple[Transaction | None, str]:
    found_at = find_date(text)
    when = found_at.replace(tzinfo=tz) if found_at else dt.datetime.now(tz)
    return parse_message(text, _reader(store, account, _default_currency(store)), when)


@router.get("/expenses/options")
def expense_options(store: OrderStore = Depends(user_store)) -> dict:
    """What the Add expense sheet offers."""
    institutions = store.institutions()
    return {
        "currency": _default_currency(store),
        "accounts": [{"key": k, "name": v} for k, v in _accounts(store).items()],
        "message_accounts": [{"key": i.key, "name": i.name} for i in institutions]
                            + [{"key": OTHER_ACCOUNT, "name": "Another account"}],
        "categories": category_options(store),
        "labels": spend_for_labels(store),
    }


class ParseRequest(BaseModel):
    text: str
    account: str | None = None  # None: guess from the message


@router.post("/expenses/parse")
def parse_pasted(body: ParseRequest, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Read a pasted SMS or notification the same way as an alert email, to check before adding."""
    if not body.text.strip():
        raise HTTPException(400, "Paste the message first.")
    institutions = {i.key: i for i in store.institutions()}
    account = body.account
    if account not in institutions and account != OTHER_ACCOUNT:
        lowered = body.text.lower()
        account = next((k for k, i in institutions.items()
                        if i.name.lower() in lowered or any(t.lower() in lowered for t in i.sender_terms)),
                       next(iter(institutions), OTHER_ACCOUNT))
    txn, reason = _parse(store, body.text, account, tz)
    if txn is None:
        return {"ok": False, "account": account,
                "reason": f"Couldn't read this message: {reason}. You can type it in instead."}
    return {"ok": True, "account": account, "direction": txn.direction, "amount": txn.amount,
            "currency": txn.currency, "description": txn.description,
            "date": txn.txn_date.astimezone(tz).date().isoformat()}


class NewExpense(BaseModel):
    how: str = "typed"            # "typed" or "message"
    text: str = ""                # the pasted message, for "message"
    account: str = CASH
    amount: float
    description: str
    date: dt.date | None = None
    category: str | None = None   # None: let the app decide
    spent_for: str | None = None  # None: let the rules decide
    note: str = ""
    force: bool = False           # add it even if it looks like it's already there


@router.post("/expenses")
def add_expense(body: NewExpense, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    if not body.amount or body.amount < 0 or not body.description.strip():
        raise HTTPException(400, "Enter the amount and what it was.")
    now = dt.datetime.now(tz)
    today = now.date()
    if body.how == "message":
        txn, reason = _parse(store, body.text, body.account, tz)
        if txn is None:
            raise HTTPException(400, f"Couldn't read this message: {reason}.")
    else:
        if body.account not in _accounts(store):
            raise HTTPException(400, "Pick how it was paid.")
        txn = Transaction(body.account, "", now, 0.0, _default_currency(store), "debit", "", "", source="manual")
    day = body.date or today
    if day > today:
        raise HTTPException(400, "That date is in the future.")
    when = txn.txn_date.astimezone(tz)
    if day != when.date():
        when = dt.datetime.combine(day, dt.time(12), tz) if day != today else now
    txn.txn_date, txn.amount, txn.description = when, float(body.amount), body.description.strip()
    txn.category = categorize(txn.description, txn.direction)

    twin = store.already_tracked(txn)
    if twin and not body.force:
        existing = store.transaction(twin)
        raise HTTPException(409, {
            "message": f"This looks like it's already there: {tidy(existing['description'])}, "
                       f"{money(existing['amount'], existing['currency'])}. Add it anyway?",
            "existing": f"txn:{twin}",
        })
    if not store.add_typed(txn):
        raise HTTPException(409, {"message": "That message was already added.", "existing": None})
    item = f"txn:{txn.txn_key}"
    if body.category:
        store.set_category(item, body.category)
    if body.spent_for and txn.direction == "debit":
        store.set_item_detail(item, "spent_for", body.spent_for)
    if body.note.strip():
        store.set_item_detail(item, "note", body.note.strip())
    reconcile(store)
    return {"message": f"Added {tidy(txn.description)}, {money(txn.amount, txn.currency)}.", "item": item}
