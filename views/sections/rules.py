"""Categories: the user's rules, their own categories, and who spending can be for."""

import pandas as pd
import streamlit as st

from order_tracker.ledger import (
    build_ledger, category_options, my_categories, set_my_categories, set_spend_for_labels, spend_for_labels,
)
from order_tracker.rules import Rule, split_words, winning_rules
from order_tracker.storage import OrderStore
from views.common import flash

EXAMPLES = pd.DataFrame([
    ("pso, total, shell", "", "", "Fuel", "Mine"),
    ("euro store", "", "5,000", "Groceries", "Home"),
    ("euro store", "", "", "Food", "Mine"),
    ("", "Bills & utilities", "", "", "Home"),
    ("zain, umar", "", "", "Going out", "Mine"),
], columns=["Merchant or payee has", "Category is", "From amount", "Set category", "Set for"])
COLUMNS = ["words", "category_is", "min_amount", "max_amount", "category", "spent_for"]


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _amount(value) -> float | None:
    return None if value is None or pd.isna(value) else float(value)


def _rule(row: dict) -> Rule:
    return Rule(split_words(_text(row["words"])), _text(row["category_is"]), _amount(row["min_amount"]),
                _amount(row["max_amount"]), _text(row["category"]), _text(row["spent_for"]))


def render(store: OrderStore) -> None:
    labels = spend_for_labels(store)
    ledger = build_ledger(store)
    spending = ledger[(ledger["amount"] > 0) & ~ledger["transfer"]]
    rules = store.rules()

    st.subheader("Rules")
    st.markdown(
        "Rules give money going out a category, say who it was for, or both. When more than one rule "
        "matches, the one with the most conditions wins, so a big shop can be *Groceries for Home* while "
        "a small one at the same store is *Food for Mine*. A change you make to one transaction always wins."
    )
    with st.expander("Examples"):
        st.dataframe(EXAMPLES, hide_index=True, key="rule_examples")
        st.caption("\"Going out\" is an example of your own category; add yours below.")

    # The transactions each rule decides: category rules look at the category the app found,
    # "For" rules at the final one, as when the ledger is built.
    deciding = pd.concat([
        winning_rules(rules, "category", spending["description"], spending["auto_category"], spending["amount"],
                      spending["amount"] > 0),
        winning_rules(rules, "spent_for", spending["description"], spending["category"], spending["amount"],
                      spending["amount"] > 0),
    ], axis=1)
    decided = [int((deciding == i).any(axis=1).sum()) for i in range(len(rules))]

    table = pd.DataFrame(
        [(", ".join(r.words), r.category_is, r.min_amount, r.max_amount, r.category, r.spent_for, decided[i])
         for i, r in enumerate(rules)],
        columns=[*COLUMNS, "matches"],
    ).astype({"min_amount": float, "max_amount": float})
    options = category_options(store, *ledger["category"], *(r.category for r in rules),
                               *(r.category_is for r in rules))
    with st.form("rules_form", border=False):
        edited = st.data_editor(
            table, key="rules_editor", num_rows="dynamic", hide_index=True, width="stretch", placeholder="",
            column_config={
                "words": st.column_config.TextColumn(
                    "Merchant or payee has", width="medium",
                    help="Words or names, separated by commas; any one of them matches. Case doesn't matter."),
                "category_is": st.column_config.SelectboxColumn("Category is", options=options),
                "min_amount": st.column_config.NumberColumn("From amount", min_value=0, format="localized"),
                "max_amount": st.column_config.NumberColumn("Up to amount", min_value=0, format="localized"),
                "category": st.column_config.SelectboxColumn("Set category", options=options),
                "spent_for": st.column_config.SelectboxColumn("Set for", options=labels),
                "matches": st.column_config.NumberColumn(
                    "Applies to", disabled=True,
                    help="Transactions this rule decides, counted when saved. A rule with more conditions "
                         "takes over the ones it also matches."),
            },
        )
        if st.form_submit_button("Save rules", type="primary"):
            filled = [_rule(row) for row in edited[COLUMNS].to_dict("records")]
            filled = [r for r in filled if r.conditions or r.category or r.spent_for]  # blank rows
            complete = [r for r in filled if r.is_complete()]
            store.save_rules(complete)
            message = f"Saved {len(complete)} rule{'s' if len(complete) != 1 else ''}."
            if len(complete) < len(filled):
                message += (f" {len(filled) - len(complete)} left out: a rule needs something to look for "
                            "and a category or For to set.")
            flash(message)
            st.rerun()
    st.caption("Add a row at the bottom of the table; select a row and press Delete to remove it.")

    st.subheader("Your lists")
    with st.form("lists_form", border=False):
        categories = st.text_input(
            "Your own categories", value=", ".join(my_categories(store)), placeholder="Going out, Clothes, Gifts",
            help="Added to the built-in categories everywhere you pick one. Separate them with commas.")
        spend_for = st.text_input(
            "Who you spend for", value=", ".join(labels),
            help="Each payment can be marked as for one of these, like yourself or your home. "
                 "The first one is used until a rule or you say otherwise.")
        if st.form_submit_button("Save lists"):
            set_my_categories(store, split_words(categories))
            if split_words(spend_for):
                set_spend_for_labels(store, split_words(spend_for))
            flash("Lists saved.")
            st.rerun()
