"""Transfers: money sent to people or accounts, which isn't counted as spending
unless it's within the user's limit, has a category, or is ticked "In spending"."""

import pandas as pd
import streamlit as st

from order_tracker.ledger import TRANSFERS, build_ledger, set_transfer_rule, transfer_rule
from order_tracker.storage import OrderStore
from views.common import compact, flash, item_editor, pick_period, viewer_timezone


def render(store: OrderStore) -> None:
    ledger = build_ledger(store)
    limit, limit_currency = transfer_rule(store)
    if not ledger.empty:
        limit_currency = ledger["currency"].value_counts().index[0] if limit == 0 else limit_currency

    with st.form("transfer_limit", border=False):
        amount_col, save_col = st.columns([3, 1], vertical_alignment="bottom")
        new_limit = amount_col.number_input(
            f"Count transfers up to this amount as spending ({limit_currency})",
            min_value=0.0, value=limit, step=500.0, format="%.0f",
            help="Small transfers, like paying a shop or a rickshaw by JazzCash or Raast, are usually "
                 "spending; big ones are often moving money. 0 counts none.",
        )
        if save_col.form_submit_button("Save", width="stretch"):
            set_transfer_rule(store, new_limit, limit_currency)
            flash(f"Transfers up to {limit_currency} {new_limit:,.0f} now count as spending." if new_limit
                  else "Transfers no longer count as spending unless you give them a category.")
            st.rerun()
    st.caption("A bigger transfer counts as spending when you tick In spending or give it a category, "
               "e.g. money you sent a friend for your share of an outing.")

    # Every transfer out, including ones the user has since given a category.
    sent = ledger[
        (ledger["amount"] > 0) & ~ledger["transfer"]
        & ((ledger["category"] == TRANSFERS) | (ledger["auto_category"] == TRANSFERS))
    ] if not ledger.empty else ledger
    if sent.empty:
        st.info("No transfers yet. Money you send to people or other accounts appears here.")
        return

    sent = sent.assign(date=sent["date"].dt.tz_convert(viewer_timezone()))
    local_day = sent["date"].dt.date
    start, end = pick_period(st, local_day.min(), local_day.max(), key="transfers_period", default="Last 3 months")
    view = sent[(local_day >= start) & (local_day <= end)]
    main = view[view["currency"] == limit_currency]
    counted = main.loc[main["counted"], "amount"].sum()
    with st.container(horizontal=True):
        st.metric(f"Sent by transfer ({limit_currency})", compact(main["amount"].sum()), border=True)
        st.metric(f"Counted as spending ({limit_currency})", compact(counted), border=True)
        st.metric(f"Not counted ({limit_currency})", compact(main["amount"].sum() - counted), border=True)

    table = pd.DataFrame({
        "date": view["date"].dt.tz_localize(None),
        "description": view["description"],
        "amount": view["amount"],
        "counted": view["counted"],
        "category": view["category"],
        "spent_for": view["spent_for"],
        "note": view["note"],
        "currency": view["currency"],
        "source": view["source"],
    }).reset_index(drop=True)
    item_editor(store, table, list(view["item"]), "transfers_editor", {
        "date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY"),
        "description": st.column_config.TextColumn("Sent to", width="medium"),
        "amount": st.column_config.NumberColumn("Amount", format="localized"),
        "currency": "Currency",
        "source": "From",
    })
