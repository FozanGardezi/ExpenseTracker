"""Every order and transaction: as a list to tap through (by day, like a banking app),
or as a table whose category, For, note and In spending can be changed in place."""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.ledger import build_ledger
from order_tracker.storage import OrderStore
from views import dialogs
from views.common import category_colors, item_editor, pick_period, theme_mode, viewer_timezone
from views.components import payment_rows, tap_list

PAGE = 60  # list rows shown at first, and added by "Show more"


def render(store: OrderStore) -> None:
    ledger = build_ledger(store)
    if ledger.empty:
        st.info("Transactions appear here after the first sync.")
        return

    ledger["date"] = ledger["date"].dt.tz_convert(viewer_timezone())
    local_day = ledger["date"].dt.date

    # The search stays in view; the rest sit behind Filters, which keeps a phone's first screen for the list.
    with st.container(horizontal=True, vertical_alignment="bottom"):
        search = st.text_input("Search", placeholder="Merchant, payee, note or email subject", key="txn_search",
                               label_visibility="collapsed", icon=":material/search:")
        filters = st.popover("Filters", icon=":material/filter_list:")
    with filters:
        start, end = pick_period(st, local_day.min(), local_day.max(), key="txn_period", default="Last 3 months")
        categories = st.multiselect("Categories", sorted(ledger["category"].unique()), placeholder="All",
                                    key="txn_categories")
        sources = st.multiselect("Sources", sorted(ledger["source"].unique()), placeholder="All", key="txn_sources")
        show_transfers = st.toggle("Transfers between my accounts", key="txn_transfers")

    view = ledger[(local_day >= start) & (local_day <= end)]
    if categories:
        view = view[view["category"].isin(categories)]
    if sources:
        view = view[view["source"].isin(sources)]
    if not show_transfers:
        view = view[~view["transfer"]]
    if search:
        needle = search.lower()
        view = view[
            view["description"].fillna("").str.lower().str.contains(needle, regex=False)
            | view["details"].fillna("").str.lower().str.contains(needle, regex=False)
            | view["note"].str.lower().str.contains(needle, regex=False)
        ]

    shown_as = st.segmented_control("Show as", ["List", "Table"], default="List", key="txn_view",
                                    label_visibility="collapsed", required=True)
    if shown_as == "List":
        _list(view, category_colors(ledger, theme_mode()), f"{start:%d %b %Y} – {end:%d %b %Y}")
        return

    table = pd.DataFrame({
        "date": view["date"].dt.tz_localize(None),
        "description": view["description"],
        "category": view["category"],
        "spent_for": view["spent_for"],
        "out": view["amount"].where(view["amount"] > 0),
        "in": (-view["amount"]).where(view["amount"] < 0),
        "currency": view["currency"],
        "counted": view["counted"],
        "note": view["note"],
        "source": view["source"],
        "paid_with": view["paid_with"],
        "details": view["details"],
    }).reset_index(drop=True)

    st.caption(f"{len(table):,} rows · click a category, For, In spending or Note to change it")
    item_editor(store, table, list(view["item"]), "txn_editor", {
        "date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, h:mm a"),
        "description": st.column_config.TextColumn("Merchant / payee", width="medium"),
        "out": st.column_config.NumberColumn("Out", format="localized"),
        "in": st.column_config.NumberColumn("In", format="localized"),
        "currency": "Currency",
        "source": "Source",
        "paid_with": "Paid with",
        "details": "Email subject",
    })
    st.download_button("Download CSV", table.to_csv(index=False), file_name="transactions.csv",
                       mime="text/csv", key="txn_download")


def _list(view: pd.DataFrame, colors: dict[str, str], span: str) -> None:
    today = dt.datetime.now(viewer_timezone()).date()
    limit = st.session_state.get("txn_limit", PAGE)
    st.caption(f"{len(view):,} rows, {span} · tap one to see it, change it, or add a note")
    picked = tap_list(payment_rows(view.head(limit), colors, today), key="txn_list", empty="Nothing matches.")
    if len(view) > limit:
        st.button("Show more", key="txn_more", width="stretch",
                  on_click=lambda: st.session_state.update(txn_limit=limit + PAGE))
    if picked:
        dialogs.open_sheet("payment", picked)
