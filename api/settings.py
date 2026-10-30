"""Settings: the account and its Gmail permission, categories and rules, skipped emails,
and the privacy notice (also public, at /privacy)."""

import datetime as dt
import html
import re

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from order_tracker import auth
from order_tracker.config import contact_email
from order_tracker.consent import PRIVACY, consent_markdown
from order_tracker.ledger import (
    build_ledger, category_options, my_categories, set_my_categories, set_spend_for_labels, spend_for_labels,
)
from order_tracker.rules import Rule, split_words, winning_rules
from order_tracker.storage import OrderStore
from order_tracker.sync import available_sources
from order_tracker.users import User, delete_user_data

from . import sync_jobs
from .auth_routes import google_config
from .common import current_user, gmail_tokens, source_name, user_store, viewer_tz

router = APIRouter(prefix="/api/settings")
public = APIRouter()


# --- Gmail & account ---

@router.get("/account")
def account(user: User = Depends(current_user), store: OrderStore = Depends(user_store), tz=Depends(viewer_tz)) -> dict:
    saved = gmail_tokens(user).load()
    sources = available_sources(store)
    granted = None
    if saved and saved.get("granted_at"):
        granted = f"{dt.datetime.fromisoformat(saved['granted_at']).astimezone(tz):%d %b %Y}"
    return {
        "user": {"name": user.name, "email": user.email},
        "gmail": {"connected": saved is not None, "account": saved["account"] if saved else None, "since": granted},
        "configured": google_config() is not None,
        "reads_from": [source.name for source in sources.values()],
        "consent": consent_markdown([source.name for source in sources.values()]),
        "queries": [{"name": source.name, "query": source.gmail_query} for source in sources.values()],
    }


@router.delete("/gmail")
def disconnect_gmail(user: User = Depends(current_user)) -> dict:
    """Withdraw the app's Gmail access at Google and forget the token."""
    tokens = gmail_tokens(user)
    saved = tokens.load()
    if saved is None:
        return {"message": "Gmail wasn't connected."}
    withdrawn = auth.revoke(saved["refresh_token"])
    tokens.delete()
    return {"message": "Gmail disconnected and the app's access withdrawn at Google." if withdrawn else
            "Gmail disconnected here, but Google couldn't be reached to withdraw access. Remove it at "
            "myaccount.google.com/permissions."}


@router.delete("/data")
def delete_data(user: User = Depends(current_user), store: OrderStore = Depends(user_store)) -> dict:
    """Remove everything stored for the user, and withdraw Gmail access. They stay signed in."""
    if sync_jobs.running(user.id):
        raise HTTPException(409, "A sync is running. Try again when it has finished.")
    saved = gmail_tokens(user).load()
    if saved:
        auth.revoke(saved["refresh_token"])
    store.close()
    delete_user_data(user.id)
    return {"message": "All your data was deleted."}


# --- Categories: rules and the user's own lists ---

class RuleIn(BaseModel):
    words: list[str] | str = []
    category_is: str = ""
    min_amount: float | None = None
    max_amount: float | None = None
    category: str = ""
    spent_for: str = ""


def _rule(row: RuleIn) -> Rule:
    words = split_words(row.words) if isinstance(row.words, str) else [w.strip() for w in row.words if w.strip()]
    return Rule(words, row.category_is.strip(), row.min_amount, row.max_amount, row.category.strip(),
                row.spent_for.strip())


@router.get("/rules")
def rules(store: OrderStore = Depends(user_store)) -> dict:
    labels = spend_for_labels(store)
    ledger = build_ledger(store)
    saved = store.rules()
    decided = [0] * len(saved)
    if not ledger.empty and saved:
        spending = ledger[(ledger["amount"] > 0) & ~ledger["transfer"].astype(bool)]
        # Category rules look at the category the app found, "For" rules at the final one,
        # as when the ledger is built.
        deciding = pd.concat([
            winning_rules(saved, "category", spending["description"], spending["auto_category"],
                          spending["amount"], spending["amount"] > 0),
            winning_rules(saved, "spent_for", spending["description"], spending["category"],
                          spending["amount"], spending["amount"] > 0),
        ], axis=1)
        decided = [int((deciding == i).any(axis=1).sum()) for i in range(len(saved))]
    return {
        "rules": [{"words": ", ".join(r.words), "category_is": r.category_is, "min_amount": r.min_amount,
                   "max_amount": r.max_amount, "category": r.category, "spent_for": r.spent_for,
                   "matches": decided[i]} for i, r in enumerate(saved)],
        "categories": category_options(store, *ledger["category"], *(r.category for r in saved),
                                       *(r.category_is for r in saved)),
        "labels": labels,
        "my_categories": my_categories(store),
        "examples": [
            {"words": "pso, total, shell", "set": "Fuel, for Mine"},
            {"words": "euro store, from 5,000", "set": "Groceries, for Home"},
            {"words": "euro store", "set": "Food, for Mine"},
            {"words": "category is Bills & utilities", "set": "for Home"},
        ],
    }


class RulesIn(BaseModel):
    rules: list[RuleIn]


@router.put("/rules")
def save_rules(body: RulesIn, store: OrderStore = Depends(user_store)) -> dict:
    filled = [r for r in map(_rule, body.rules) if r.conditions or r.category or r.spent_for]  # not blank
    complete = [r for r in filled if r.is_complete()]
    store.save_rules(complete)
    message = f"Saved {len(complete)} rule{'s' if len(complete) != 1 else ''}."
    if len(complete) < len(filled):
        message += (f" {len(filled) - len(complete)} left out: a rule needs something to look for "
                    "and a category or For to set.")
    return {"message": message, "saved": len(complete)}


class ListsIn(BaseModel):
    categories: list[str] | str = []
    spend_for: list[str] | str = []


def _list(value: list[str] | str) -> list[str]:
    return split_words(value) if isinstance(value, str) else [v.strip() for v in value if v.strip()]


@router.put("/lists")
def save_lists(body: ListsIn, store: OrderStore = Depends(user_store)) -> dict:
    set_my_categories(store, _list(body.categories))
    if _list(body.spend_for):
        set_spend_for_labels(store, _list(body.spend_for))
    return {"message": "Lists saved."}


# --- skipped emails ---

@router.get("/skipped")
def skipped(sources: list[str] = Query(default=[]), store: OrderStore = Depends(user_store),
            tz=Depends(viewer_tz)) -> dict:
    """Emails from tracked senders that weren't turned into an order or transaction, and why."""
    frame = store.skipped_frame()
    if frame.empty:
        return {"rows": [], "sources": []}
    frame = frame.assign(source=frame["provider"].map(lambda key: source_name(key, store)))
    names = sorted(frame["source"].unique())
    if sources:
        frame = frame[frame["source"].isin(sources)]
    return {
        "sources": names,
        "rows": [{"received": f"{r.received_at.tz_convert(tz):%d %b %Y, %I:%M %p}".replace(", 0", ", "),
                  "source": r.source, "subject": r.subject, "sender": r.sender, "reason": r.reason}
                 for r in frame.head(500).itertuples()],
        "total": len(frame),
    }


# --- privacy ---

def _privacy() -> str:
    email = contact_email()
    return PRIVACY + (f"\n### Contact\nQuestions about your data: {email}\n" if email else "")


@public.get("/api/privacy")
def privacy() -> dict:
    return {"markdown": _privacy()}


@public.get("/privacy", response_class=HTMLResponse)
def privacy_page() -> str:
    """The privacy notice as a web page, readable without signing in (Google's review links to it)."""
    blocks = []
    for block in _privacy().strip().split("\n\n"):
        lines = [line.strip() for line in block.splitlines()]
        if lines[0].startswith("### "):
            blocks.append(f"<h2>{_inline(lines.pop(0)[4:])}</h2>")
            if not lines:
                continue
        if lines[0].startswith("- "):
            items: list[str] = []
            for line in lines:  # an item's text may carry on over the next lines
                if line.startswith("- "):
                    items.append(line[2:])
                else:
                    items[-1] += " " + line
            blocks.append("<ul>" + "".join(f"<li>{_inline(item)}</li>" for item in items) + "</ul>")
        else:
            blocks.append(f"<p>{_inline(' '.join(lines))}</p>")
    return ("<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            "<title>Privacy · Expense Tracker</title><body style='font-family:system-ui;max-width:40rem;"
            f"margin:2rem auto;padding:0 1rem;line-height:1.5'><h1>Privacy</h1>{''.join(blocks)}</body></html>")


def _inline(text: str) -> str:
    """Escape, then **bold**, `code` and [links](https://...)."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return re.sub(r"\[(.+?)\]\((https://[^)\s]+)\)", r'<a href="\2">\1</a>', text)
