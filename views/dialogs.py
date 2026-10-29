"""Sheets that pop up over a page: one payment (to change or remove it), adding an
expense (typed in, or pasted from a bank's SMS or notification), and the payments
behind a figure (a category, a place, a limit).

A page opens a sheet with open_sheet; app.py shows it after the page, on every run
until it's dismissed or its work is done. (A sheet opened only on the run of the
tap would close on any other rerun, such as a theme switch.)"""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.alerts import find_date, parse_message
from order_tracker.budgets import Budget, Limit, budget_for, month_key
from order_tracker.categories import categorize
from order_tracker.ledger import ADDED_BY_YOU, OTHER_ACCOUNT, build_ledger, category_options, spend_for_labels
from order_tracker.models import Institution, Transaction
from order_tracker.money import money
from order_tracker.reconcile import reconcile
from order_tracker.storage import CASH, OrderStore
from views.common import esc, flash, open_store, tidy, viewer_timezone
from views.components import payment_rows, tap_list

SHEET_ITEM = "sheet_item"  # the payment opened from a list inside a sheet
OPEN_SHEET = "open_sheet"  # (sheet name, args, kwargs) of the sheet that's open


def open_sheet(name: str, *args, **kwargs) -> None:
    st.session_state[OPEN_SHEET] = (name, args, kwargs)


def close_sheet() -> None:
    st.session_state.pop(OPEN_SHEET, None)


def show_open_sheet() -> None:
    """Show the sheet that's open, if any; app.py calls this after the page."""
    if OPEN_SHEET in st.session_state:
        name, args, kwargs = st.session_state[OPEN_SHEET]
        {"payment": payment, "payments": payments, "add_expense": add_expense}[name](*args, **kwargs)


def done(message: str) -> None:
    """Close the sheet and redraw the page, with a message."""
    close_sheet()
    flash(message)
    st.rerun()


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
    name = f"<b>{esc(tidy(row['description']))}</b>"
    if row["kind"] == "Order":
        paid = f", paid with <b>{esc(row['paid_with'])}</b>" if row["paid_with"] else ""
        return f"{esc(row['source'])} from {name}{paid} on {when}"
    if row["came_from"] == "Added by you":
        paid = "in cash" if row["kind"] == "Cash" else f"from <b>{esc(row['source'])}</b>"
        return f"{name}, paid {paid} on {when}"
    account = f"<b>{esc(row['source'])}</b>"
    if row["amount"] < 0:
        return f"Received from {name} into {account} on {when}"
    return f"Paid to {name} from {account} on {when}"


def payment_editor(store: OrderStore, row: pd.Series, key: str) -> None:
    """One payment, like a banking app's detail sheet: change its category, who it was
    for, its note and whether it counts; or, for something the user added, everything."""
    tz = viewer_timezone()
    today = dt.datetime.now(tz).date()
    money_out = row["amount"] > 0
    typed = row["came_from"] in ADDED_BY_YOU
    st.html(f'<div class="sheet-amount"><div class="muted">Amount</div>'
            f'<div class="big">{"-" if money_out else "+"}{esc(money(abs(row["amount"]), row["currency"]))}</div>'
            f'<div class="muted">{_sentence(row)}</div></div>')
    txn = store.transaction(row["item"][4:]) if row["item"].startswith("txn:") else None
    accounts = _accounts(store)
    labels = spend_for_labels(store)

    with st.form(f"{key}_{row['item']}", border=False):
        if typed:
            amount = st.number_input("Amount", value=float(abs(row["amount"])), min_value=0.0, step=50.0, format="%.0f")
            description = st.text_input("What was it?", value=row["description"])
            day = st.date_input("Date", value=row["date"].date(), max_value=today, format="DD/MM/YYYY")
            account_keys = list(accounts) + ([txn["institution"]] if txn["institution"] not in accounts else [])
            account = st.selectbox("Paid with", account_keys, index=account_keys.index(txn["institution"]),
                                   format_func=lambda k: accounts.get(k, row["source"]))
        options = category_options(store, row["category"])
        category = st.selectbox("Category", options, index=options.index(row["category"]))
        spent_for = None
        if money_out:
            spent_for = st.segmented_control(
                "For", list(dict.fromkeys(labels + [row["spent_for"]])), default=row["spent_for"],
                help="Who it was for. Leave both off to go back to what your rules say.")
        note = st.text_input("Note", value=row["note"], placeholder='e.g. "Outing with Zain"')
        counted = row["counted"]
        if row["transfer"]:
            st.caption("This moved money between your own accounts, so it isn't spending or income.")
        else:
            counted = st.toggle("Count as spending" if money_out else "Count as money in", value=bool(row["counted"]))
        save = st.form_submit_button("Save", type="primary", width="stretch")

    if save:
        item = row["item"]
        if category != row["category"]:
            store.set_category(item, category)
        if money_out and spent_for != row["spent_for"]:
            store.set_item_detail(item, "spent_for", spent_for)
        if note.strip() != row["note"]:
            store.set_item_detail(item, "note", note.strip() or None)
        if counted != row["counted"]:
            store.set_item_detail(item, "counted", counted)
        if typed:
            when = row["date"] if day == row["date"].date() else dt.datetime.combine(day, dt.time(12), tz)
            if not amount or not description.strip():
                st.warning("Enter the amount and what it was.")
                return
            store.update_typed(txn["txn_key"], when, amount, description.strip(), account)
            reconcile(store)
        done("Saved.")

    details = [("Came from", row["came_from"]), ("When", _when(row)),
               ("Account", row["paid_with"] if row["kind"] == "Order" else row["source"])]
    if txn and txn.get("reference"):
        details.append(("Reference", txn["reference"]))
    if row["details"] and not typed:
        details.append(("Email subject", row["details"]))
    if row["came_from"] == "Pasted message" and txn:
        details.append(("Message", txn["subject"]))
    st.markdown("**Details**")
    st.html('<table class="details">' + "".join(f"<tr><td class='muted'>{esc(label)}</td><td>{esc(value)}</td></tr>"
                                                 for label, value in details if value) + "</table>")
    if typed and st.button("Remove this expense", icon=":material/delete:", key=f"{key}_remove"):
        store.delete_typed(txn["txn_key"])
        reconcile(store)
        done(f"Removed {tidy(row['description'])}.")


@st.dialog("Details", width="medium", on_dismiss=close_sheet)
def payment(item: str) -> None:
    store = open_store()
    ledger = build_ledger(store)
    found = ledger[ledger["item"] == item]
    if found.empty:
        st.info("This payment isn't there any more.")
        return
    row = found.iloc[0].copy()
    row["date"] = row["date"].tz_convert(viewer_timezone())
    payment_editor(store, row, "payment")


@st.dialog("Payments", width="medium", on_dismiss=close_sheet)
def payments(title: str, subtitle: str, items: list[str], colors: dict[str, str],
             limit: Limit | None = None, suggested: float = 0.0) -> None:
    """The payments behind a figure, newest first. Tapping one opens it in the same sheet;
    `limit` offers to keep this in check with a monthly limit."""
    store = open_store()
    tz = viewer_timezone()
    ledger = build_ledger(store)
    ledger["date"] = ledger["date"].dt.tz_convert(tz)
    rows = ledger[ledger["item"].isin(items)]
    picked = st.session_state.get(SHEET_ITEM)
    if picked in set(rows["item"]):
        if st.button("Back", icon=":material/arrow_back:", type="tertiary", key="sheet_back"):
            st.session_state.pop(SHEET_ITEM, None)
            st.rerun(scope="fragment")
        payment_editor(store, rows[rows["item"] == picked].iloc[0], "sheet")
        return

    st.markdown(f"### {esc(title)}")
    st.caption(subtitle)
    if limit is not None:
        with st.form("sheet_limit", border=False):
            amount_col, save_col = st.columns([2, 1], vertical_alignment="bottom")
            amount = amount_col.number_input(
                "Keep it in check: a monthly limit", min_value=0.0, step=500.0, format="%.0f",
                value=float(suggested) or None, placeholder="Amount")
            if save_col.form_submit_button("Set limit", width="stretch") and amount:
                _save_limit(store, Limit(limit.name, amount, limit.category, limit.words), tz)
                done(f"{limit.name}: a limit of {money(amount)} a month. It shows on Home.")
    today = dt.datetime.now(tz).date()
    tapped = tap_list(payment_rows(rows, colors, today, by_day=False), key="sheet_list",
                      empty="Nothing here.")
    if tapped:
        st.session_state[SHEET_ITEM] = tapped
        st.rerun(scope="fragment")


def open_payments(*args, **kwargs) -> None:
    """Open the payments sheet afresh (not on a payment opened last time)."""
    st.session_state.pop(SHEET_ITEM, None)
    open_sheet("payments", *args, **kwargs)


def _save_limit(store: OrderStore, limit: Limit, tz) -> None:
    """Add (or replace, by name) a limit in the budget, from this month on."""
    this_month = dt.datetime.now(tz).date().replace(day=1)
    budget = budget_for(store.budgets(), this_month)
    limits = [existing for existing in budget.limits if existing.name.lower() != limit.name.lower()] + [limit]
    store.save_budget(month_key(this_month), Budget(budget.total, limits))


@st.dialog("Add an expense", on_dismiss=close_sheet)
def add_expense(currency: str) -> None:
    """Something the emails don't show, like cash for samosas; or a bank's SMS or app
    notification, pasted in and read the same way as an alert email."""
    store = open_store()
    tz = viewer_timezone()
    now = dt.datetime.now(tz)
    how = st.segmented_control("How", ["Type it in", "Paste a bank message"], default="Type it in",
                               key="add_how", label_visibility="collapsed", required=True)
    accounts = _accounts(store)
    institutions = {i.key: i for i in store.institutions()}

    if how == "Paste a bank message":
        text = st.text_area("The SMS or notification", key="add_text", height=110,
                            placeholder="e.g. PKR 750 paid to DOUBLE SHOT from A/c **1234 on 05-Oct-2026 18:05")
        if not text.strip():
            st.caption("Copy the message from your bank or wallet (SMS or app notification) and paste it here. "
                       "Its amount, payee and date are read the same way as an alert email.")
            return
        lowered = text.lower()
        guess = next((k for k, i in institutions.items()
                      if i.name.lower() in lowered or any(t.lower() in lowered for t in i.sender_terms)),
                     next(iter(institutions), OTHER_ACCOUNT))
        keys = list(institutions) + [OTHER_ACCOUNT]
        source = st.selectbox("From", keys, index=keys.index(guess), key=f"add_from_{hash(text)}",
                              format_func=lambda k: institutions[k].name if k in institutions else "Another account")
        reader = institutions.get(source) or Institution(OTHER_ACCOUNT, "Another account", "bank", [], currency=currency)
        found_at = find_date(text)
        txn, reason = parse_message(text, reader, found_at.replace(tzinfo=tz) if found_at else now)
        if txn is None:
            st.warning(f"Couldn't read this message: {reason}. You can type it in instead.")
            return
        _confirm(store, txn, accounts, f"paste_{hash(text)}_{source}", tz)
        return

    blank = Transaction(CASH, "", now, 0.0, currency, "debit", "", "", source="manual")
    _confirm(store, blank, accounts, "typed", tz)


def _confirm(store: OrderStore, txn: Transaction, accounts: dict[str, str], key: str, tz) -> None:
    """The form both ways of adding share: check (or type) the details, then add."""
    today = dt.datetime.now(tz).date()
    labels = spend_for_labels(store)
    money_in = txn.direction == "credit"
    with st.form(f"add_{key}", border=False):
        if txn.source == "message":
            st.caption(("Money in" if money_in else "Money out") + " · check the details, then add it.")
        amount = st.number_input("Amount", min_value=0.0, step=50.0, format="%.0f", key=f"{key}_amount",
                                 value=float(txn.amount) or None, placeholder="0")
        what = "What was it?" if txn.source == "manual" else "From" if money_in else "Paid to"
        description = st.text_input(what, value=txn.description, key=f"{key}_what",
                                    placeholder="e.g. Samosas, Petrol, Gas bill")
        typed = txn.source == "manual"
        left, right = st.columns(2) if typed else (st, None)
        day = left.date_input("Date", value=txn.txn_date.astimezone(tz).date(), max_value=today,
                              key=f"{key}_day", format="DD/MM/YYYY")
        account = txn.institution
        if typed:  # a pasted message's account is picked above the form
            keys = list(accounts)
            account = right.selectbox("Paid with", keys, index=keys.index(account) if account in keys else 0,
                                      format_func=accounts.get, key=f"{key}_account")
        options = category_options(store)
        category = st.selectbox("Category", options, index=None, placeholder="Let the app decide",
                                key=f"{key}_category")
        spent_for = None
        if not money_in:
            spent_for = st.segmented_control("For", labels, key=f"{key}_for",
                                             help="Leave both off to let your rules decide.")
        note = st.text_input("Note", key=f"{key}_note", placeholder='e.g. "Outing with Zain"')
        add = st.form_submit_button("Add", type="primary", width="stretch")
    if not add:
        return
    if not amount or not description.strip():
        st.warning("Enter the amount and what it was.")
        return

    when = txn.txn_date.astimezone(tz)
    if day != when.date():
        when = dt.datetime.combine(day, dt.time(12), tz) if day != today else dt.datetime.now(tz)
    txn.txn_date, txn.amount, txn.description, txn.institution = when, amount, description.strip(), account
    txn.category = categorize(txn.description, txn.direction)
    twin = store.already_tracked(txn)
    force = f"{key}_force"
    if twin and not st.session_state.get(force):
        st.session_state[force] = True
        existing = store.transaction(twin)
        st.warning(f"This looks like it's already there: {tidy(existing['description'])}, "
                   f"{money(existing['amount'], existing['currency'])}. Press Add again to add it anyway.")
        return
    st.session_state.pop(force, None)
    if not store.add_typed(txn):
        st.info("That message was already added.")
        return
    item = f"txn:{txn.txn_key}"
    if category:
        store.set_category(item, category)
    if spent_for:
        store.set_item_detail(item, "spent_for", spent_for)
    if note.strip():
        store.set_item_detail(item, "note", note.strip())
    reconcile(store)
    done(f"Added {tidy(txn.description)}, {money(amount, txn.currency)}.")
