"""Activity: every transaction, monthly statements, transfers, and delivery orders."""

import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel

from order_tracker.insights import months as month_of
from order_tracker.ledger import TRANSFERS, annotate, build_ledger, set_transfer_rule, transfer_rule
from order_tracker.money import money
from order_tracker.parsers import PROVIDERS
from order_tracker.storage import OrderStore

from .common import (
    PERIODS, category_slots, clock, currencies, group_of, local_ledger, month_key, parse_month, payment_rows,
    resolve_period, short_date, span_text, tidy, today_in, user_store, viewer_tz,
)

router = APIRouter(prefix="/api/activity")

PAGE = 60  # list rows sent at a time; the app asks for more as the list scrolls


# --- Transactions ---

def _filtered(ledger: pd.DataFrame, today: dt.date, period, start, end, search, categories, sources, transfers):
    local_day = ledger["date"].dt.date
    choice, first, last = resolve_period(period, local_day.min(), local_day.max(), today, start, end,
                                         default="Last 3 months")
    view = ledger[(local_day >= first) & (local_day <= last)]
    if categories:
        view = view[view["category"].isin(categories)]
    if sources:
        view = view[view["source"].isin(sources)]
    if not transfers:
        view = view[~view["transfer"].astype(bool)]
    if search:
        needle = search.lower()
        view = view[
            view["description"].fillna("").str.lower().str.contains(needle, regex=False)
            | view["details"].fillna("").str.lower().str.contains(needle, regex=False)
            | view["note"].str.lower().str.contains(needle, regex=False)
        ]
    return view, choice, first, last


@router.get("/transactions")
def transactions(period: str | None = None, start: dt.date | None = None, end: dt.date | None = None,
                 search: str = "", categories: list[str] = Query(default=[]), sources: list[str] = Query(default=[]),
                 transfers: bool = False, offset: int = 0, limit: int = PAGE,
                 store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Everything, newest first, listed by day. Tap one to see it, change it, or add a note."""
    ledger = local_ledger(store, tz)
    today = today_in(tz)
    if ledger.empty:
        return {"empty": True, "rows": [], "total": 0, "periods": PERIODS}
    view, choice, first, last = _filtered(ledger, today, period, start, end, search.strip(), categories, sources,
                                          transfers)
    offset, limit = max(offset, 0), min(max(limit, 1), 500)
    return {
        "empty": False, "total": len(view), "offset": offset, "slots": _main_slots(ledger),
        "rows": payment_rows(view.iloc[offset:offset + limit], today),
        "caption": f"{len(view):,} rows, {span_text(first, last)} · tap one to see it, change it, or add a note",
        "period": choice, "start": first.isoformat(), "end": last.isoformat(), "periods": PERIODS,
        "options": {"categories": sorted(ledger["category"].unique()), "sources": sorted(ledger["source"].unique())},
    }


@router.get("/transactions.csv")
def transactions_csv(period: str | None = None, start: dt.date | None = None, end: dt.date | None = None,
                     search: str = "", categories: list[str] = Query(default=[]),
                     sources: list[str] = Query(default=[]), transfers: bool = False,
                     store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> Response:
    """The same rows as a spreadsheet, to save or share."""
    ledger = local_ledger(store, tz)
    if ledger.empty:
        return Response("", media_type="text/csv")
    view, *_ = _filtered(ledger, today_in(tz), period, start, end, search.strip(), categories, sources, transfers)
    table = pd.DataFrame({
        "date": view["date"].dt.tz_localize(None),
        "description": view["description"],
        "category": view["category"],
        "for": view["spent_for"],
        "out": view["amount"].where(view["amount"] > 0),
        "in": (-view["amount"]).where(view["amount"] < 0),
        "currency": view["currency"],
        "in_spending": view["counted"],
        "note": view["note"],
        "source": view["source"],
        "paid_with": view["paid_with"],
        "email_subject": view["details"],
    })
    return Response(table.to_csv(index=False), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="transactions.csv"'})


def _main_slots(ledger: pd.DataFrame) -> dict[str, int]:
    """Category colors, ranked in the most used currency (as Overview ranks them)."""
    return category_slots(ledger[ledger["currency"] == currencies(ledger)[0]])


# --- Statements ---

@router.get("/statements")
def statements(bank: str = "all", currency: str | None = None, month: str | None = None,
               store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Spending for each month from the monthly statements, and one month's transactions."""
    data = store.statement_transactions()
    if data.empty:
        return {"empty": True}
    today = today_in(tz)
    names = {i.key: i.name for i in store.institutions()}
    # The same rules as everywhere else: categories, rules, who it was for, and what counts.
    data["item"] = "txn:" + data["txn_key"]
    data["money_out"] = data["amount"].where(data["direction"] == "debit", 0.0)
    data["money_in"] = data["amount"].where(data["direction"] == "credit", 0.0)
    data = annotate(data.assign(amount=data["money_out"] - data["money_in"], transfer=data["transfer_id"].notna()),
                    store)
    data["date"] = data["txn_date"].dt.tz_convert(tz)
    data["month"] = month_of(data["date"])
    data["out"] = data["money_out"].where(data["counted"], 0.0)
    data["in"] = data["money_in"].where(data["counted"], 0.0)

    banks = sorted(data["institution"].unique(), key=lambda k: names.get(k, k))
    seen = currencies(data)
    currency = currency if currency in seen else seen[0]
    bank = bank if bank in banks else "all"
    view = data[data["currency"] == currency]
    if bank != "all":
        view = view[view["institution"] == bank]
    monthly = view.groupby("month").agg(spent=("out", "sum"), received=("in", "sum"),
                                        transactions=("txn_key", "size")).sort_index()
    ledger = build_ledger(store)
    slots = category_slots(ledger[ledger["currency"] == currency])
    spending = view[view["out"] > 0]
    by_group = spending.assign(group=spending["category"].map(lambda c: group_of(c, slots)))
    table = by_group.pivot_table(index="month", columns="group", values="out", aggfunc="sum", fill_value=0)
    order = list(table.sum().sort_values(ascending=False).index)
    chart = [{
        "month": month_key(m), "label": f"{m:%b}", "year": m.year,
        "total": float(table.loc[m].sum()) if m in table.index else 0.0,
        "total_text": money(table.loc[m].sum() if m in table.index else 0, currency, short=True),
        "budget": None,
        "segments": [{"group": g, "value": float(table.at[m, g])} for g in order
                     if m in table.index and table.at[m, g] > 0],
    } for m in monthly.index]

    choices = list(monthly.index.sort_values(ascending=False))
    picked = parse_month(month)
    picked = picked if picked in choices else choices[0]
    selected = view[view["month"] == picked].sort_values("date", ascending=False)
    spent, received = selected["out"].sum(), selected["in"].sum()
    by_category = selected[selected["out"] > 0].groupby("category")["out"].sum().sort_values(ascending=False)
    return {
        "empty": False, "currency": currency, "currencies": seen, "bank": bank,
        "banks": [{"key": "all", "name": "All banks and wallets"}] + [{"key": k, "name": names.get(k, k)} for k in banks],
        "slots": slots, "chart": chart,
        "months": [{"key": month_key(m), "label": f"{m:%B %Y}"} for m in choices],
        "months_table": [{
            "month": f"{m:%B %Y}", "spent": money(r.spent, currency), "received": money(r.received, currency),
            "net": money(r.received - r.spent, currency), "count": int(r.transactions),
        } for m, r in monthly.sort_index(ascending=False).iterrows()],
        "month": month_key(picked), "month_label": f"{picked:%B}",
        "summary": [
            {"label": "Spent", "value": money(spent, currency, short=True)},
            {"label": "Received", "value": money(received, currency, short=True)},
            {"label": "Net", "value": money(received - spent, currency, short=True)},
            {"label": "Transactions", "value": f"{len(selected):,}"},
        ],
        "by_category": [{"category": c, "group": group_of(c, slots), "value": float(v), "amount": money(v, currency)}
                        for c, v in by_category.items()],
        "rows": [_statement_row(row, names, today) for row in selected.itertuples()],
    }


def _statement_row(row, names: dict[str, str], today: dt.date) -> dict:
    money_in = row.money_in > 0
    amount = row.money_in if money_in else row.money_out
    sub = f"{row.category} · {names.get(row.institution, row.institution)}"
    if row.note:
        sub += f" · {row.note}"
    when = short_date(row.date.date(), today)
    # A statement row paid for a delivery order is shown (and changed) as that order.
    item = f"order:{row.matched_order}" if isinstance(row.matched_order, str) else row.item
    return {"id": item, "title": tidy(row.description) or "Statement entry", "sub": sub,
            "amount": ("+" if money_in else "") + money(amount, row.currency),
            "meta": when if row.counted else f"{when} · not counted", "money_in": bool(money_in),
            "category": row.category, "day": row.date.date().isoformat(), "day_label": when}


# --- Transfers ---

@router.get("/transfers")
def transfers(period: str | None = None, start: dt.date | None = None, end: dt.date | None = None,
              store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Money sent to people or accounts, which isn't counted as spending unless it's within the
    limit, has a category, or is ticked In spending."""
    ledger = local_ledger(store, tz)
    limit, limit_currency = transfer_rule(store)
    if not ledger.empty and limit == 0:
        limit_currency = currencies(ledger)[0]
    base = {"limit": limit, "limit_currency": limit_currency, "periods": PERIODS}
    if ledger.empty:
        return {**base, "empty": True}
    # Every transfer out, including ones the user has since given a category.
    sent = ledger[(ledger["amount"] > 0) & ~ledger["transfer"].astype(bool)
                  & ((ledger["category"] == TRANSFERS) | (ledger["auto_category"] == TRANSFERS))]
    if sent.empty:
        return {**base, "empty": True}
    today = today_in(tz)
    local_day = sent["date"].dt.date
    choice, first, last = resolve_period(period, local_day.min(), local_day.max(), today, start, end,
                                         default="Last 3 months")
    view = sent[(local_day >= first) & (local_day <= last)]
    main = view[view["currency"] == limit_currency]
    total, counted = main["amount"].sum(), main.loc[main["counted"], "amount"].sum()
    return {
        **base, "empty": False, "period": choice, "start": first.isoformat(), "end": last.isoformat(),
        "slots": _main_slots(ledger),
        "summary": [
            {"label": "Sent by transfer", "value": money(total, limit_currency, short=True)},
            {"label": "Counted as spending", "value": money(counted, limit_currency, short=True)},
            {"label": "Not counted", "value": money(total - counted, limit_currency, short=True)},
        ],
        "rows": payment_rows(view, today, by_day=False),
    }


class TransferLimit(BaseModel):
    limit: float
    currency: str | None = None


@router.put("/transfers/limit")
def save_transfer_limit(body: TransferLimit, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    current, currency = transfer_rule(store)
    if body.currency:
        currency = body.currency
    elif current == 0:
        seen = currencies(local_ledger(store, tz))
        currency = seen[0] if seen else currency
    amount = max(float(body.limit), 0.0)
    set_transfer_rule(store, amount, currency)
    return {"message": f"Transfers up to {money(amount, currency)} now count as spending." if amount
            else "Transfers no longer count as spending unless you give them a category."}


# --- Delivery orders ---

@router.get("/orders")
def orders(services: list[str] = Query(default=[]), period: str | None = None, start: dt.date | None = None,
           end: dt.date | None = None, currency: str | None = None, search: str = "",
           store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Foodpanda, Careem, inDrive and Krave Mart: by service, by merchant, every order."""
    frame = store.orders_frame()
    if frame.empty:
        return {"empty": True, "periods": PERIODS}
    today = today_in(tz)
    frame["date"] = frame["order_date"].dt.tz_convert(tz)
    local_day = frame["date"].dt.date
    present = [k for k in PROVIDERS if k in set(frame["provider"])]
    chosen = [k for k in services if k in present] or present
    choice, first, last = resolve_period(period, local_day.min(), local_day.max(), today, start, end)
    seen = currencies(frame)
    currency = currency if currency in seen else seen[0]
    view = frame[frame["provider"].isin(chosen) & (frame["currency"] == currency)
                 & (local_day >= first) & (local_day <= last)]
    base = {
        "empty": False, "services": [{"key": k, "name": PROVIDERS[k].name} for k in present],
        "chosen": chosen, "period": choice, "start": first.isoformat(), "end": last.isoformat(),
        "periods": PERIODS, "currencies": seen, "currency": currency,
    }
    if view.empty:
        return {**base, "nothing": True}

    purchases = view[view["amount"] > 0]
    net = view["amount"].sum()
    n_months = (last.year - first.year) * 12 + last.month - first.month + 1
    average = purchases["amount"].mean() if len(purchases) else None
    monthly = view.assign(month=month_of(view["date"])).groupby(["month", "provider"])["amount"].sum()
    by_service = view.groupby("provider")["amount"].sum()
    top = (view.groupby(["merchant", "provider"], as_index=False)
           .agg(orders=("amount", "size"), spent=("amount", "sum"))
           .sort_values("spent", ascending=False).head(10))
    listed = view
    if search.strip():
        needle = search.strip().lower()
        listed = view[view["merchant"].fillna("").str.lower().str.contains(needle, regex=False)
                      | view["subject"].fillna("").str.lower().str.contains(needle, regex=False)]
    return {
        **base, "nothing": False,
        "summary": [
            {"label": "Total spent", "value": money(net, currency, short=True), "help": "Orders minus refunds."},
            {"label": "Orders", "value": f"{len(purchases):,}", "help": None},
            {"label": "Average order", "value": money(average, currency) if average else "–", "help": None},
            {"label": "Per month", "value": money(net / n_months, currency, short=True),
             "help": f"Averaged over the {n_months} month(s) in the period."},
        ],
        "chart": [{
            "month": month_key(m), "label": f"{m:%b}", "year": m.year,
            "total": float(monthly.loc[m].sum()), "total_text": money(monthly.loc[m].sum(), currency, short=True),
            "budget": None,
            "segments": [{"group": p, "value": float(v)} for p, v in monthly.loc[m].items() if v > 0],
        } for m in sorted(monthly.index.get_level_values(0).unique())],
        "by_service": [{"key": k, "name": PROVIDERS[k].name, "value": float(by_service[k]),
                        "amount": money(by_service[k], currency)} for k in PROVIDERS if k in by_service.index],
        "top_merchants": [{"merchant": r.merchant, "service": PROVIDERS[r.provider].name, "orders": int(r.orders),
                           "spent": money(r.spent, currency)} for r in top.itertuples()],
        "orders": [{
            "id": f"order:{r.order_key}", "title": tidy(r.merchant) or PROVIDERS[r.provider].name,
            "sub": f"{PROVIDERS[r.provider].name} · {r.category}", "amount": money(r.amount, r.currency),
            "meta": f"{short_date(r.date.date(), today)}, {clock(r.date)}",
            "money_in": bool(r.amount < 0), "category": r.category, "service": r.provider,
        } for r in listed.head(300).itertuples()],
        "orders_total": len(listed),
    }
