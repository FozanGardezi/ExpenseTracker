"""Statements: spending for each month, and each month's transactions by category."""

import pandas as pd
import streamlit as st

from order_tracker.ledger import annotate, build_ledger
from order_tracker.storage import OrderStore
from views.common import (
    CHART_CONFIG, NEUTRAL, category_colors, clicked_month, compact, item_editor, labelled_bars, local_month,
    stacked_months, style_figure, theme_mode, viewer_timezone,
)


def render(store: OrderStore) -> None:
    data = store.statement_transactions()
    if data.empty:
        st.info(
            "Monthly statements appear here once they've been read. If your bank locks them "
            "with a password, add it under **Accounts → Statement settings**."
        )
        return
    mode = theme_mode()
    names = {i.key: i.name for i in store.institutions()}

    # The same rules as everywhere else: categories, rules, who it was for, and what counts.
    data["item"] = "txn:" + data["txn_key"]
    data["money_out"] = data["amount"].where(data["direction"] == "debit", 0.0)
    data["money_in"] = data["amount"].where(data["direction"] == "credit", 0.0)
    data = annotate(data.assign(amount=data["money_out"] - data["money_in"], transfer=data["transfer_id"].notna()),
                    store)
    data["date"] = data["txn_date"].dt.tz_convert(viewer_timezone())
    data["month"] = local_month(data["date"])
    data["out"] = data["money_out"].where(data["counted"], 0.0)
    data["in"] = data["money_in"].where(data["counted"], 0.0)

    banks = sorted(data["institution"].unique(), key=lambda k: names.get(k, k))
    currencies = data["currency"].value_counts().index.tolist()
    # Pickers only appear when there's a choice to make, which keeps the phone layout short.
    bank, currency = "all", currencies[0]
    if len(banks) > 1 or len(currencies) > 1:
        f1, f2 = st.columns([2, 1])
        if len(banks) > 1:
            bank = f1.selectbox(
                "Bank or wallet", ["all", *banks], key="stmt_bank",
                format_func=lambda k: "All banks and wallets" if k == "all" else names.get(k, k),
            )
        if len(currencies) > 1:
            currency = f2.selectbox("Currency", currencies, key="stmt_currency")
    view = data[data["currency"] == currency]
    if bank != "all":
        view = view[view["institution"] == bank]

    monthly = view.groupby("month").agg(
        spent=("out", "sum"), received=("in", "sum"), transactions=("txn_key", "size")
    ).sort_index()
    monthly["net"] = monthly["received"] - monthly["spent"]

    st.subheader("Spending each month")
    ledger = build_ledger(store)
    colors = category_colors(ledger[ledger["currency"] == currency], mode)
    spending = view[view["out"] > 0]
    months = list(monthly.index.sort_values(ascending=False))
    version = st.session_state.get("stmt_chart_version", 0)
    chart_key = f"stmt_chart_{version}"

    def open_clicked_month() -> None:
        month = clicked_month(st.session_state[chart_key])
        if month in months:
            st.session_state["stmt_month"] = month

    if not spending.empty:
        fig = stacked_months(spending.assign(amount=spending["out"]), colors, currency, mode)
        st.plotly_chart(style_figure(fig, mode, 340), theme=None, config=CHART_CONFIG, key=chart_key,
                        on_select=open_clicked_month, selection_mode="points")
    st.caption("Click a month's bar to see what it went on.")
    with st.expander("Month by month"):
        st.dataframe(
            monthly.sort_index(ascending=False).reset_index(), hide_index=True, key="stmt_monthly",
            column_config={
                "month": st.column_config.DateColumn("Month", format="MMMM YYYY"),
                "spent": st.column_config.NumberColumn(f"Spent ({currency})", format="localized"),
                "received": st.column_config.NumberColumn(f"Received ({currency})", format="localized"),
                "net": st.column_config.NumberColumn(f"Net ({currency})", format="localized"),
                "transactions": st.column_config.NumberColumn("Transactions"),
            },
        )

    if st.session_state.get("stmt_month") not in months:  # e.g. after changing the bank
        st.session_state.pop("stmt_month", None)
    month = st.selectbox(
        "Month", months, key="stmt_month", format_func=lambda m: f"{m:%B %Y}",
        # Picking from the list clears the chart's highlighted bar, so the two never disagree.
        on_change=lambda: st.session_state.update(stmt_chart_version=version + 1),
    )
    selected = view[view["month"] == month].sort_values("date")
    spent, received = selected["out"].sum(), selected["in"].sum()
    with st.container(horizontal=True):
        st.metric(f"Spent ({currency})", compact(spent), border=True, help=f"{currency} {spent:,.2f}")
        st.metric(f"Received ({currency})", compact(received), border=True, help=f"{currency} {received:,.2f}")
        st.metric(f"Net ({currency})", compact(received - spent), border=True)
        st.metric("Transactions", f"{len(selected):,}", border=True)

    by_category = selected[selected["out"] > 0].groupby("category")["out"].sum().sort_values(ascending=False)
    if not by_category.empty:
        st.subheader(f"{month:%B} by category")
        st.plotly_chart(
            labelled_bars(list(by_category.index), list(by_category.values),
                          [colors.get(c, NEUTRAL[mode]) for c in by_category.index], currency, mode),
            theme=None, config=CHART_CONFIG, key="stmt_categories",
        )

    st.subheader(f"{month:%B} transactions")
    table = pd.DataFrame({
        "date": selected["date"].dt.date,
        "description": selected["description"],
        "category": selected["category"],
        "spent_for": selected["spent_for"],
        "out": selected["money_out"].where(selected["money_out"] > 0),
        "in": selected["money_in"].where(selected["money_in"] > 0),
        "counted": selected["counted"],
        "note": selected["note"],
        "bank": selected["institution"].map(lambda k: names.get(k, k)),
    }).reset_index(drop=True)
    st.caption("Click a category, For, In spending or Note to change it.")
    item_editor(store, table, list(selected["item"]), "stmt_editor", {
        "date": st.column_config.DateColumn("Date", format="D MMM"),
        "description": st.column_config.TextColumn("Description", width="medium"),
        "out": st.column_config.NumberColumn("Out", format="localized"),
        "in": st.column_config.NumberColumn("In", format="localized"),
        "bank": "Bank or wallet",
    })
