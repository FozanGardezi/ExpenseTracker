"""Home → Budget: how much to spend in a month, and limits on parts of it, like
eating out, petrol, or one coffee shop."""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.budgets import Budget, Limit, budget_for, month_key
from order_tracker.insights import months, usual
from order_tracker.ledger import build_ledger, category_options
from order_tracker.money import money
from order_tracker.rules import split_words
from order_tracker.storage import OrderStore
from views.common import card, flash, viewer_timezone

EXAMPLES = pd.DataFrame([
    ("Eating out", "Food", "", "15,000"),
    ("Groceries", "Groceries", "", "30,000"),
    ("Petrol", "Fuel", "", "20,000"),
    ("Bills", "Bills & utilities", "", "25,000"),
    ("Coffee", "", "double shot, gloria jeans", "3,000"),
], columns=["Name", "Category", "Places with these words", "Monthly limit"])
COLUMNS = ["name", "category", "words", "amount"]


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def render(store: OrderStore) -> None:
    tz = viewer_timezone()
    this_month = dt.datetime.now(tz).date().replace(day=1)
    saved = store.budgets()
    budget = budget_for(saved, this_month)
    ledger = build_ledger(store)
    currency = ledger["currency"].value_counts().index[0] if not ledger.empty else "PKR"
    spending = ledger[ledger["counted"] & (ledger["amount"] > 0) & (ledger["currency"] == currency)]
    spending = spending.assign(month=months(spending["date"].dt.tz_convert(tz))) if not spending.empty \
        else spending.assign(month=pd.Series(dtype=object))
    this = spending[spending["month"] == this_month]
    usual_month = float(usual(spending.assign(all="all"), this_month, "all").get("all", 0.0))

    def usual_for(limit: Limit) -> float:
        matched = spending[limit.matches(spending)].assign(all="all")
        return float(usual(matched, this_month, "all").get("all", 0.0)) if not matched.empty else 0.0

    table = pd.DataFrame(
        [(limit.name, limit.category, ", ".join(limit.words), limit.amount,
          this.loc[limit.matches(this), "amount"].sum(), usual_for(limit)) for limit in budget.limits],
        columns=[*COLUMNS, "spent", "usual"],
    ).astype({"amount": float, "spent": float, "usual": float}).round({"spent": 0, "usual": 0})
    options = category_options(store, *ledger["category"], *(limit.category for limit in budget.limits))

    with card("budget_form"):
        st.html('<p class="card-title">Your monthly budget</p>')
        with st.form("budget_form", border=False):
            total = st.number_input(
                f"How much you want to spend in a month ({currency})", min_value=0.0, step=5000.0, format="%.0f",
                value=budget.total, placeholder="No budget yet",
                help="Everything counted as spending, for everyone you spend for.")
            if usual_month:
                st.caption(f"Your usual month: about {money(usual_month, currency)} (the average of the last "
                           "three months).")
            st.markdown("**Limits** (optional)")
            st.caption("Keep part of your spending in check: a category, places whose name has certain words, "
                       "or both.")
            edited = st.data_editor(
                table, key="limits_editor", num_rows="dynamic", hide_index=True, width="stretch", placeholder="",
                column_config={
                    "name": st.column_config.TextColumn("Name", help="What to call it, e.g. Eating out."),
                    "category": st.column_config.SelectboxColumn("Category", options=options),
                    "words": st.column_config.TextColumn(
                        "Places with these words", width="medium",
                        help="Words or names, separated by commas; any one matches. Case doesn't matter."),
                    "amount": st.column_config.NumberColumn("Monthly limit", min_value=0, format="localized"),
                    "spent": st.column_config.NumberColumn("This month", disabled=True, format="localized"),
                    "usual": st.column_config.NumberColumn(
                        "Usual month", disabled=True, format="localized",
                        help="The average of up to three months before this one, counted when saved."),
                },
            )
            if st.form_submit_button("Save budget", type="primary"):
                limits, skipped = [], 0
                for row in edited[COLUMNS].to_dict("records"):
                    name, category, words = _text(row["name"]), _text(row["category"]), split_words(_text(row["words"]))
                    amount = None if row["amount"] is None or pd.isna(row["amount"]) else float(row["amount"])
                    if not (name or category or words or amount):
                        continue  # a blank row
                    if not amount or not (category or words):
                        skipped += 1
                        continue
                    limits.append(Limit(name or category or ", ".join(words), amount, category, words))
                store.save_budget(month_key(this_month), Budget(total or None, limits))
                message = "Budget saved."
                if skipped:
                    message += (f" {skipped} limit{'s' if skipped > 1 else ''} left out: a limit needs an amount "
                                "and a category or words to look for.")
                flash(message)
                st.rerun()
        st.caption("Add a limit at the bottom of the table; select a row and press Delete to remove it. "
                   f"Changes apply from {this_month:%B %Y} on; earlier months keep the budget they had.")

    with st.expander("Examples"):
        st.dataframe(EXAMPLES, hide_index=True, key="limit_examples")
        st.caption("A limit with words follows one place, like a coffee shop, whatever its category. "
                   "You can also set one from a place's or category's payments on Overview or Places.")
    if len(saved) > 1:
        with st.expander("Earlier budgets"):
            st.dataframe(
                pd.DataFrame([(dt.datetime.strptime(start, "%Y-%m"), b.total, len(b.limits))
                              for start, b in sorted(saved.items(), reverse=True)],
                             columns=["from", "total", "limits"]),
                hide_index=True, key="budget_history",
                column_config={"from": st.column_config.DateColumn("From", format="MMMM YYYY"),
                               "total": st.column_config.NumberColumn("Budget", format="localized"),
                               "limits": "Limits"},
            )
