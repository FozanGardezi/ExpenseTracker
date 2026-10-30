"""Home: status and setup steps, syncing, and the four sub-tabs (Overview, Trends, Places,
Budget), plus the payments behind any figure on them."""

import calendar
import datetime as dt

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from order_tracker.budgets import Budget, Limit, add_months, budget_for, pace
from order_tracker.budgets import month_key as budget_month_key
from order_tracker.insights import insights, place_key, place_name, usual
from order_tracker.institutions import STATEMENT_PREFIX
from order_tracker.ledger import category_options, spend_for_labels
from order_tracker.money import money
from order_tracker.rules import split_words
from order_tracker.storage import OrderStore
from order_tracker.sync import available_sources
from order_tracker.users import User

from . import sync_jobs
from .common import (
    EVERYTHING_ELSE, category_slots, currencies, current_user, gmail_tokens, group_of, local_ledger,
    month_key, month_label, parse_month, payment_rows, plural, rounded, today_in, user_store, viewer_tz,
)

router = APIRouter(prefix="/api/home")
sync_router = APIRouter(prefix="/api/sync")

AUTO_SYNC_AFTER = dt.timedelta(hours=6)
LOOKBACK_OPTIONS = [30, 90, 180, 365, 730, 1095]
STATUS_LABELS = {"over": "Over budget", "heading over": "Heading over", "on track": "On track",
                 "under": "Under budget"}
TREND_RANGES = {"6": 6, "12": 12, "all": None}
PLACE_PERIODS = {1: "This month", 3: "3 months", 12: "12 months"}


# --- status, setup steps and syncing ---

@router.get("/status")
def home_status(user: User = Depends(current_user), store: OrderStore = Depends(user_store),
                tz=Depends(viewer_tz)) -> dict:
    connected = gmail_tokens(user).load() is not None
    last = store.last_sync()
    steps = [
        {"label": "Allow read-only Gmail access", "done": connected, "target": "settings"},
        {"label": "Add the banks and wallets you use", "done": bool(store.institutions()), "target": "accounts"},
        {"label": "Run your first sync with Sync now", "done": last is not None, "target": "sync"},
    ]
    status = "Gmail connected" if connected else "Gmail not connected"
    status += f" · last synced {last.astimezone(tz):%d %b, %H:%M}" if last else " · not synced yet"
    txn_currencies = currencies(store.transactions_frame())
    return {
        "first_name": user.name.split()[0] if user.name else user.email,
        "gmail_connected": connected,
        "last_sync": last.isoformat() if last else None,
        "status": status,
        "steps": steps if not all(s["done"] for s in steps) else [],
        "currency": txn_currencies[0] if txn_currencies else "PKR",
        "sync": _job(user),
    }


def _job(user: User) -> dict | None:
    job = sync_jobs.status(user.id)
    return job.public() if job else None


@sync_router.get("/options")
def sync_options(store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    sources = available_sources(store)
    today = today_in(tz)
    return {
        "sources": [{"key": key, "name": source.name} for key, source in sources.items()],
        "statement_sources": [{"key": key, "name": source.institution.name}
                              for key, source in sources.items() if key.startswith(STATEMENT_PREFIX)],
        "lookback": LOOKBACK_OPTIONS,
        "default_days": 365,
        "years": list(range(today.year, today.year - 15, -1)),
    }


@sync_router.get("")
def sync_status(user: User = Depends(current_user)) -> dict:
    return {"job": _job(user)}


class SyncRequest(BaseModel):
    sources: list[str] | None = None  # None: everything
    days: int = 365
    rescan: bool = False              # forget what was read from these sources and read it again
    auto: bool = False                # only if the last sync is older than AUTO_SYNC_AFTER


@sync_router.post("")
def start_sync(body: SyncRequest, user: User = Depends(current_user),
               store: OrderStore = Depends(user_store)) -> dict:
    if gmail_tokens(user).load() is None:
        if body.auto:
            return {"started": False, "reason": "Gmail isn't connected."}
        raise HTTPException(409, "Gmail isn't connected. Allow it under Settings → Gmail & account.")
    if body.auto:
        last = store.last_sync()
        if last is not None and dt.datetime.now(dt.UTC) - last <= AUTO_SYNC_AFTER:
            return {"started": False, "reason": "Synced recently."}
    days = body.days if body.days in LOOKBACK_OPTIONS else 365
    started = sync_jobs.start(user, body.sources, days, rescan=body.rescan)
    return {"started": started, "reason": "" if started else "A sync is already running.", "job": _job(user)}


class OlderStatements(BaseModel):
    sources: list[str]          # stmt:<key> sources
    year: int
    months: list[int] = []      # empty: the whole year


@sync_router.post("/older")
def read_older_statements(body: OlderStatements, user: User = Depends(current_user), tz=Depends(viewer_tz)) -> dict:
    """Statements for an earlier year or months. A month's statement arrives in the weeks after it."""
    today = today_in(tz)
    chosen = sorted(m for m in body.months if 1 <= m <= 12)
    first, final = (chosen[0], chosen[-1]) if chosen else (1, 12)
    since = dt.date(body.year, first, 1)
    if since > today:
        raise HTTPException(400, "Those months haven't happened yet.")
    until = min(dt.date(body.year, final, calendar.monthrange(body.year, final)[1]) + dt.timedelta(days=45),
                today + dt.timedelta(days=1))
    keys = [k for k in body.sources if k.startswith(STATEMENT_PREFIX)]
    if not keys:
        raise HTTPException(400, "Pick at least one bank or wallet.")
    if gmail_tokens(user).load() is None:
        raise HTTPException(409, "Gmail isn't connected. Allow it under Settings → Gmail & account.")
    started = sync_jobs.start(user, keys, since=since, until=until)
    return {"started": started, "reason": "" if started else "A sync is already running.",
            "searching": f"Statement emails received {since:%d %b %Y} – {until:%d %b %Y}.", "job": _job(user)}


# --- Overview: one month at a glance ---

def _month_choices(ledger: pd.DataFrame, today: dt.date) -> list[dt.date]:
    first = min(ledger["month"].min(), today.replace(day=1)) if not ledger.empty else today.replace(day=1)
    choices = []
    while (month := add_months(today, -len(choices))) >= first:
        choices.append(month)
    return choices


def _scope(store, tz, month, spent_for, currency):
    """What Overview and its sheets look at: (ledger in one currency, color slots, labels,
    counted spending for the chosen label, the month, the currency, the label, today)."""
    ledger = local_ledger(store, tz)
    today = today_in(tz)
    labels = spend_for_labels(store)
    choices = _month_choices(ledger, today)
    picked = parse_month(month)
    month_date = picked if picked in choices else choices[0]
    seen = currencies(ledger)
    currency = currency if currency in seen else (seen[0] if seen else "PKR")
    spent_for = spent_for if spent_for in labels else "All"
    view = ledger[ledger["currency"] == currency]
    slots = category_slots(view)
    if spent_for != "All":
        view = view[view["spent_for"] == spent_for]
    spending = view[view["counted"] & (view["amount"] > 0)]
    return ledger, view, slots, labels, spending, month_date, currency, spent_for, today, choices, seen


@router.get("/overview")
def overview(month: str | None = None, spent_for: str = "All", currency: str | None = None,
             store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    (ledger, view, slots, labels, spending, month_date, currency, spent_for, today, choices,
     seen) = _scope(store, tz, month, spent_for, currency)
    base = {
        "months": [{"key": month_key(m), "label": month_label(m, today)} for m in choices],
        "month": month_key(month_date), "labels": labels, "for": spent_for,
        "currencies": seen, "currency": currency, "slots": slots,
    }
    if ledger.empty:
        return {**base, "empty": True}
    this = spending[spending["month"] == month_date]
    in_month = view[view["month"] == month_date]
    budget = budget_for(store.budgets(), month_date)
    progress = pace(this["amount"].sum(), budget.total, month_date, today)
    return {
        **base,
        "empty": False,
        "hero": _hero(this, spending, in_month, month_date, spent_for, progress, currency, labels),
        "budget": _budget(progress, budget, spending, month_date, today, currency) if spent_for == "All" else None,
        "limits": _limits(budget.limits, this, month_date, today, currency),
        "where": _where_it_went(this, spending, month_date, today, slots, currency),
        "insights": [
            {"id": f"{i.kind}:{i.key}", "kind": i.kind, "key": i.key, "title": i.title, "text": i.text,
             "level": i.level, "category": i.category}
            for i in insights(spending, month_date, today, budget, currency)[:5]
        ],
        "insights_empty": "Nothing stands out" + (" so far this month." if month_date == today.replace(day=1) else ".")
                          + " Places you pay often, or far more than usual, show up here.",
        "recent": payment_rows(in_month[~in_month["transfer"].astype(bool)].head(8), today),
    }


def _hero(this, spending, in_month, month, spent_for, progress, currency, labels) -> dict:
    spent = this["amount"].sum()
    current = not progress.finished
    who = "" if spent_for == "All" else f" for {spent_for}"
    sub = f"That's about **{money(progress.per_day, currency)}** a day."
    if not current:
        before = spending.loc[spending["month"] == add_months(month, -1), "amount"].sum()
        if before:
            change = spent - before
            sub += (f" **{money(abs(change), currency)} {'more' if change > 0 else 'less'}** "
                    f"than {add_months(month, -1):%B}.")
    notes = []
    split = this.groupby("spent_for")["amount"].sum().reindex(labels).dropna()
    if spent_for == "All" and len(split) > 1:
        notes.append(" · ".join(f"{label} {money(amount, currency)}" for label, amount in split.items()))
    received = -in_month.loc[in_month["counted"] & (in_month["amount"] < 0), "amount"].sum()
    if received and spent_for == "All":
        notes.append(f"{money(received, currency)} came in{' this month' if current else ''}: income and refunds.")
    transfers = in_month["transfer"].astype(bool)
    not_counted = in_month[~in_month["counted"] & ~transfers & (in_month["amount"] > 0)]["amount"].sum()
    return {
        "label": f"You've spent{who} so far this month" if current else f"You spent{who} in {month:%B %Y}",
        "value": money(spent, currency, short=True),
        "sub": sub,
        "notes": notes,
        "not_counted": f"{money(not_counted, currency)} sent by transfer isn't counted as spending."
                       if not_counted else None,
    }


def _budget(progress, budget, spending, month, today, currency) -> dict:
    if not budget.total:
        usual_month = usual(spending.assign(all="all"), today.replace(day=1), "all").get("all", 0.0)
        return {"set": False, "title": f"{month:%B} budget",
                "hint": f"Your usual month is about {money(usual_month, currency)}." if usual_month else None}
    remaining = f"{progress.days_left} days remaining" if progress.days_left else f"{progress.days} days"
    explanation = [
        f"**Spent:** {money(progress.spent, currency)} of your {money(progress.budget, currency)} budget. "
        "It counts payments from your bank and wallet emails, statements, delivery receipts and what you "
        "added, each once. Moves between your own accounts, and transfers you haven't marked as "
        "spending, aren't counted.",
        f"**Per day:** {money(progress.per_day, currency)} over {progress.elapsed} of {progress.days} days.",
    ]
    if not progress.finished:
        explanation.append(f"**At this pace** the month ends near {money(progress.projected, currency)}.")
    explanation.append("Change the budget under **Budget**.")
    return {
        "set": True, "title": f"{month:%B} budget", "status": progress.status,
        "status_label": STATUS_LABELS[progress.status], "used": progress.used,
        "used_text": f"{progress.used:.0%} used", "remaining": remaining,
        "sentence": _budget_sentence(progress, currency), "explanation": explanation,
    }


def _budget_sentence(progress, currency) -> str:
    left = money(abs(progress.left), currency, short=True)
    if progress.status == "over":
        return f"You're **{left}** past your budget."
    if progress.status == "under":
        return f"You stayed **{left}** under budget."
    per_day = money(progress.left / max(progress.days_left, 1), currency)
    if progress.status == "heading over":
        return (f"**{left}** left. At this pace you'll spend about "
                f"**{money(progress.projected, currency, short=True)}**; {per_day} a day keeps you on budget.")
    return f"**{left}** left: about **{per_day}** a day for the {progress.days_left} days to go."


def _limits(limits: list[Limit], this, month, today, currency) -> list[dict]:
    rows = []
    for position, limit in enumerate(limits):
        covered = this[limit.matches(this)]
        progress = pace(covered["amount"].sum(), limit.amount, month, today)
        category = limit.category or (covered["category"].mode().iloc[0] if not covered.empty else "")
        rows.append({
            "position": position, "title": limit.name, "category": category, "status": progress.status,
            "sub": f"{money(-progress.left, currency)} over" if progress.status == "over"
            else f"{money(progress.left, currency)} left",
            "amount": money(progress.spent, currency), "meta": f"of {money(limit.amount, currency)}",
            "share": progress.used or 0.0,
        })
    return rows


def _where_it_went(this, spending, month, today, slots, currency) -> dict:
    by_category = this.groupby("category")["amount"].sum().sort_values(ascending=False)
    if by_category.empty:
        return {"count": 0, "categories": [], "donut": [], "top": None, "top_share": None}
    before = usual(spending, month, "category")
    total = by_category.sum()
    # A month still going is only compared once it has passed the usual, not while it's catching up.
    going = month == today.replace(day=1)
    rows = []
    for category, amount in by_category.items():
        count = int((this["category"] == category).sum())
        sub = plural(count, "payment")
        was = before.get(category)
        if was is not None:
            change = amount - was
            if abs(change) < 0.1 * max(was, 1):
                sub += "" if going else " · about usual"
            elif change > 0 or not going:
                sub += f" · {money(abs(change), currency, short=True)} {'above' if change > 0 else 'below'} usual"
        rows.append({"category": category, "group": group_of(category, slots), "sub": sub,
                     "amount": money(amount, currency), "meta": f"{amount / total:.0%}", "value": float(amount)})
    groups = by_category.groupby(lambda c: group_of(c, slots)).sum().sort_values(ascending=False)
    groups = pd.concat([groups.drop(EVERYTHING_ELSE, errors="ignore"), groups.filter([EVERYTHING_ELSE])])
    return {
        "count": len(by_category), "categories": rows,
        "donut": [{"group": group, "value": float(value)} for group, value in groups.items()],
        "top": by_category.idxmax(), "top_share": f"{by_category.max() / total:.0%}",
    }


# --- the payments behind a figure ---

@router.get("/drill")
def drill(kind: str, key: str = "", month: str | None = None, spent_for: str = "All",
          currency: str | None = None, period: int = 3, store: OrderStore = Depends(user_store),
          tz=Depends(viewer_tz)) -> dict:
    """The payments behind a figure, newest first, and a monthly limit to offer for them.

    kind: "category" (a category this month), "limit" (a limit, by position), "place"
    (a place this month, by place key), "trend" (a month, optionally one category group,
    key "YYYY-MM|group"), "places" (a place over the last `period` months), "search"
    (anything whose name has these words, over all time).
    """
    (ledger, view, slots, labels, spending, month_date, currency, spent_for, today, _,
     _) = _scope(store, tz, month, spent_for, currency)
    this = spending[spending["month"] == month_date]
    offer: Limit | None = None
    suggested = 0.0
    if kind == "category":
        rows, title = this[this["category"] == key], key
        offer = Limit(key, 0, key)
        suggested = rounded(usual(spending, month_date, "category").get(key, 0.0))
        subtitle = f"{month_date:%B %Y} · {plural(len(rows), 'payment')} · {money(rows['amount'].sum(), currency)}"
    elif kind == "limit":
        limits = budget_for(store.budgets(), month_date).limits
        if not key.isdigit() or int(key) >= len(limits):
            raise HTTPException(404, "That limit isn't there any more.")
        limit = limits[int(key)]
        rows, title = this[limit.matches(this)], limit.name
        subtitle = (f"{month_date:%B %Y} · {plural(len(rows), 'payment')} · "
                    f"{money(rows['amount'].sum(), currency)} of {money(limit.amount, currency)}")
    elif kind == "place":
        rows = this[this["description"].map(place_key) == key]
        title = place_name(rows["description"]) or key
        offer = Limit(title, 0, words=[key])
        history = spending[spending["month"] < month_date]
        matched = history[offer.matches(history)].assign(all="all")
        suggested = rounded(float(usual(matched, month_date, "all").get("all", 0.0))) if not matched.empty else 0.0
        subtitle = f"{month_date:%B %Y} · {plural(len(rows), 'payment')} · {money(rows['amount'].sum(), currency)}"
    elif kind == "trend":
        trend_month, _, group = key.partition("|")
        picked_month = parse_month(trend_month)
        rows = spending[spending["month"] == picked_month]
        if group:
            rows = rows[rows["category"].map(lambda c: group_of(c, slots)) == group]
        title = f"{group} in {picked_month:%B %Y}" if group else f"{picked_month:%B %Y}" if picked_month else key
        if group == EVERYTHING_ELSE:
            title += f" ({', '.join(sorted(rows['category'].unique()))})"
        subtitle = f"{plural(len(rows), 'payment')} · {money(rows['amount'].sum(), currency)}"
    elif kind == "places":
        period = period if period in PLACE_PERIODS else 3
        start = add_months(today, 1 - period)
        places = spending.assign(place=spending["description"].map(place_key))
        rows = places[(places["month"] >= start) & (places["place"] == key)]
        title = place_name(rows["description"]) or key
        offer = Limit(title, 0, words=[key])
        suggested = rounded(rows["amount"].sum() / period)
        subtitle = (f"{plural(len(rows), 'payment')} {_place_span(start, period)} · "
                    f"{money(rows['amount'].sum(), currency)}")
    elif kind == "search":
        rows = spending[spending["description"].fillna("").str.lower().str.contains(key.lower(), regex=False)]
        title = f"“{key}”"
        whole_words = Limit(key.title(), 0, words=[key])
        offer = whole_words if not rows.empty and whole_words.matches(rows).all() else None
        if not rows.empty:
            suggested = rounded(rows["amount"].sum() / _months_seen(rows))
        subtitle = f"{plural(len(rows), 'payment')} · {money(rows['amount'].sum(), currency)}"
    else:
        raise HTTPException(400, f"Unknown kind: {kind}")
    return {
        "title": title, "subtitle": subtitle, "currency": currency, "slots": slots,
        "rows": payment_rows(rows.sort_values("date", ascending=False), today, by_day=False),
        "limit": {"name": offer.name, "category": offer.category, "words": offer.words} if offer else None,
        "suggested": suggested or None,
    }


def _place_span(start: dt.date, period: int) -> str:
    return f"in {start:%B}" if period == 1 else f"since {start:%B %Y}"


def _months_seen(rows: pd.DataFrame) -> int:
    first, last = pd.Timestamp(rows["month"].min()), pd.Timestamp(rows["month"].max())
    return (last.to_period("M") - first.to_period("M")).n + 1


# --- Trends: past months side by side ---

@router.get("/trends")
def trends(span_key: str = Query("12", alias="range"), spent_for: str = "All", currency: str | None = None,
           store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    ledger = local_ledger(store, tz)
    today = today_in(tz)
    labels = spend_for_labels(store)
    seen = currencies(ledger)
    currency = currency if currency in seen else (seen[0] if seen else "PKR")
    spent_for = spent_for if spent_for in labels else "All"
    span_key = span_key if span_key in TREND_RANGES else "12"
    base = {"labels": labels, "for": spent_for, "currencies": seen, "currency": currency, "range": span_key,
            "ranges": [{"key": "6", "label": "6 months"}, {"key": "12", "label": "12 months"},
                       {"key": "all", "label": "All"}]}
    view = ledger[ledger["currency"] == currency]
    slots = category_slots(view)
    if spent_for != "All":
        view = view[view["spent_for"] == spent_for]
    spending = view[view["counted"] & (view["amount"] > 0)]
    if spending.empty:
        return {**base, "empty": True, "slots": slots}

    this_month = today.replace(day=1)
    span = TREND_RANGES[span_key]
    start = spending["month"].min() if span is None else max(spending["month"].min(), add_months(today, 1 - span))
    shown = spending[spending["month"] >= start]
    totals = shown.groupby("month")["amount"].sum().sort_index()
    finished = totals[totals.index < this_month]
    stats = []
    if len(finished):
        stats += [
            {"label": "Usual month", "value": money(finished.tail(3).mean(), currency, short=True),
             "help": "The average of the last three finished months."},
            {"label": "Highest", "value": money(finished.max(), currency, short=True),
             "help": f"{finished.idxmax():%B %Y}"},
            {"label": "Lowest", "value": money(finished.min(), currency, short=True),
             "help": f"{finished.idxmin():%B %Y}"},
        ]
    stats.append({"label": "This month so far", "value": money(totals.get(this_month, 0.0), currency, short=True),
                  "help": None})

    saved = store.budgets()
    budgets = {m: budget_for(saved, m).total for m in totals.index}
    by_group = shown.assign(group=shown["category"].map(lambda c: group_of(c, slots)))
    table = by_group.pivot_table(index="month", columns="group", values="amount", aggfunc="sum", fill_value=0)
    order = [g for g in table.sum().sort_values(ascending=False).index if g != EVERYTHING_ELSE]
    if EVERYTHING_ELSE in table:
        order.append(EVERYTHING_ELSE)
    chart = [{
        "month": month_key(m), "label": f"{m:%b}", "year": m.year, "total": float(totals[m]),
        "total_text": money(totals[m], currency, short=True),
        "budget": float(budgets[m]) if spent_for == "All" and budgets[m] else None,
        "segments": [{"group": g, "value": float(table.at[m, g])} for g in order if table.at[m, g] > 0],
    } for m in totals.index]
    counted = view[view["counted"]]
    received = -counted[counted["amount"] < 0].groupby("month")["amount"].sum()
    return {
        **base, "empty": False, "slots": slots, "stats": stats, "chart": chart, "groups": order,
        "rest": sorted(set(by_group.loc[by_group["group"] == EVERYTHING_ELSE, "category"])),
        "categories": _trend_categories(spending, this_month, currency),
        "months_table": [{
            "month": f"{m:%B %Y}", "spent": money(totals[m], currency),
            "budget": money(budgets[m], currency) if budgets[m] else "–",
            "left": money(budgets[m] - totals[m], currency) if budgets[m] else "–",
            "received": money(received.get(m, 0.0), currency),
        } for m in sorted(totals.index, reverse=True)],
    }


def _trend_categories(spending: pd.DataFrame, this_month: dt.date, currency: str) -> list[dict]:
    """Each category this month against its usual, with its last six months."""
    six = [add_months(this_month, -i) for i in range(5, -1, -1)]
    by_month = (spending[spending["month"].isin(six)].pivot_table(
        index="category", columns="month", values="amount", aggfunc="sum", fill_value=0.0)
        .reindex(columns=six, fill_value=0.0))
    before = usual(spending, this_month, "category")
    rows = []
    for category, history in by_month.iterrows():
        now, was = float(history[this_month]), float(before.get(category, 0.0))
        rows.append({
            "category": category, "now": money(now, currency), "usual": money(was, currency),
            "change": f"{100 * (now - was) / was:+.0f}%" if was > 0 else "new", "sort": (was, now),
            "trend": [float(v) for v in history.tolist()],
        })
    rows.sort(key=lambda r: r.pop("sort"), reverse=True)
    return rows


# --- Places: where the money goes, place by place ---

@router.get("/places")
def places(period: int = 3, sort: str = "spent", search: str = "", store: OrderStore = Depends(user_store),
           tz=Depends(viewer_tz)) -> dict:
    ledger = local_ledger(store, tz)
    today = today_in(tz)
    period = period if period in PLACE_PERIODS else 3
    periods = [{"key": k, "label": v} for k, v in PLACE_PERIODS.items()]
    if ledger.empty:
        return {"empty": True, "period": period, "periods": periods}
    currency = currencies(ledger)[0]
    view = ledger[ledger["currency"] == currency]
    slots = category_slots(view)
    spending = view[view["counted"] & (view["amount"] > 0)]
    spending = spending.assign(place=spending["description"].map(place_key))
    start = add_months(today, 1 - period)
    shown = spending[spending["month"] >= start]
    span = _place_span(start, period)

    six = [add_months(today, -i) for i in range(5, -1, -1)]
    rows = []
    for place, group in shown.groupby("place"):
        history = spending[(spending["place"] == place) & spending["month"].isin(six)]
        rows.append({
            "place": place, "name": place_name(group["description"]), "category": group["category"].mode().iloc[0],
            "times": len(group), "spent_value": float(group["amount"].sum()),
            "spent": money(group["amount"].sum(), currency), "each": money(group["amount"].mean(), currency),
            "trend": [float(v) for v in history.groupby("month")["amount"].sum().reindex(six, fill_value=0.0)],
        })
    by = ("times", "spent_value") if sort == "often" else ("spent_value", "times")
    rows.sort(key=lambda r: (r[by[0]], r[by[1]]), reverse=True)

    found = None
    if search.strip():
        needle = search.strip()
        matched = spending[spending["description"].fillna("").str.lower().str.contains(needle.lower(), regex=False)]
        if matched.empty:
            found = {"search": needle, "empty": True, "text": f"Nothing matches “{needle}”."}
        else:
            recent = matched[matched["month"] >= start]
            per_month = matched["amount"].sum() / _months_seen(matched)
            found = {"search": needle, "empty": False, "text": (
                f"**{money(recent['amount'].sum(), currency)}** {span}, {plural(len(recent), 'time')}. "
                f"Over all your history: **{money(matched['amount'].sum(), currency)}**, about "
                f"**{money(per_month, currency)} a month**.")}
    return {"empty": False, "period": period, "periods": periods, "sort": "often" if sort == "often" else "spent",
            "currency": currency, "slots": slots, "span": span,
            "caption": f"Everywhere you paid {span}, biggest first. Tap one to see its payments.",
            "places": rows, "found": found}


# --- Budget: a monthly budget and limits on parts of it ---

class LimitIn(BaseModel):
    name: str = ""
    category: str = ""
    words: list[str] | str = []
    amount: float | None = None


class BudgetIn(BaseModel):
    total: float | None = None
    limits: list[LimitIn] | None = None  # None keeps the current limits


def _words(words: list[str] | str) -> list[str]:
    return split_words(words) if isinstance(words, str) else [w.strip() for w in words if w.strip()]


@router.get("/budget")
def get_budget(store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    this_month = today_in(tz).replace(day=1)
    saved = store.budgets()
    budget = budget_for(saved, this_month)
    ledger = local_ledger(store, tz)
    currency = currencies(ledger)[0] if not ledger.empty else "PKR"
    spending = ledger[ledger["counted"] & (ledger["amount"] > 0) & (ledger["currency"] == currency)]
    this = spending[spending["month"] == this_month]
    usual_month = float(usual(spending.assign(all="all"), this_month, "all").get("all", 0.0))

    def usual_for(limit: Limit) -> float:
        matched = spending[limit.matches(spending)].assign(all="all")
        return float(usual(matched, this_month, "all").get("all", 0.0)) if not matched.empty else 0.0

    return {
        "currency": currency, "total": budget.total, "from": f"{this_month:%B %Y}",
        "usual_month": money(usual_month, currency) if usual_month else None,
        "limits": [{
            "name": limit.name, "category": limit.category, "words": ", ".join(limit.words), "amount": limit.amount,
            "spent": money(this.loc[limit.matches(this), "amount"].sum(), currency),
            "usual": money(usual_for(limit), currency),
        } for limit in budget.limits],
        "categories": category_options(store, *ledger["category"], *(limit.category for limit in budget.limits)),
        "history": [{"from": dt.datetime.strptime(start, "%Y-%m").strftime("%B %Y"),
                     "total": money(b.total, currency) if b.total else "–", "limits": len(b.limits)}
                    for start, b in sorted(saved.items(), reverse=True)] if len(saved) > 1 else [],
        "examples": [
            {"name": "Eating out", "category": "Food", "words": "", "amount": "15,000"},
            {"name": "Petrol", "category": "Fuel", "words": "", "amount": "20,000"},
            {"name": "Coffee", "category": "", "words": "double shot, gloria jeans", "amount": "3,000"},
        ],
    }


@router.put("/budget")
def save_budget(body: BudgetIn, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Save the budget from this month on; earlier months keep the budget they had."""
    this_month = today_in(tz).replace(day=1)
    current = budget_for(store.budgets(), this_month)
    limits, skipped = current.limits, 0
    if body.limits is not None:
        limits = []
        for row in body.limits:
            name, category, words = row.name.strip(), row.category.strip(), _words(row.words)
            if not (name or category or words or row.amount):
                continue  # a blank row
            if not row.amount or not (category or words):
                skipped += 1
                continue
            limits.append(Limit(name or category or ", ".join(words), float(row.amount), category, words))
    store.save_budget(budget_month_key(this_month), Budget(body.total or None, limits))
    message = "Budget saved."
    if skipped:
        message += (f" {skipped} limit{'s' if skipped > 1 else ''} left out: a limit needs an amount "
                    "and a category or words to look for.")
    return {"message": message, "saved": len(limits), "skipped": skipped}


@router.post("/budget/limits")
def add_limit(body: LimitIn, store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    """Add (or replace, by name) one limit, from this month on: "keep it in check" on a sheet."""
    words = _words(body.words)
    if not body.amount or not (body.category or words) or not body.name.strip():
        raise HTTPException(400, "A limit needs a name, an amount, and a category or words to look for.")
    this_month = today_in(tz).replace(day=1)
    budget = budget_for(store.budgets(), this_month)
    limit = Limit(body.name.strip(), float(body.amount), body.category, words)
    limits = [existing for existing in budget.limits if existing.name.lower() != limit.name.lower()] + [limit]
    store.save_budget(budget_month_key(this_month), Budget(budget.total, limits))
    return {"message": f"{limit.name}: a limit of {money(limit.amount)} a month. It shows on Home."}
