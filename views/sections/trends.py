"""Home → Trends: past months side by side, against the budget, and how each
category moves from month to month."""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.budgets import add_months, budget_for
from order_tracker.insights import months, usual
from order_tracker.ledger import build_ledger, spend_for_labels
from order_tracker.money import money
from order_tracker.storage import OrderStore
from views import dialogs
from views.common import (
    CHART_CONFIG, EVERYTHING_ELSE, card, category_colors, category_group, clicked_group, clicked_month,
    stacked_months, style_figure, theme_mode, viewer_timezone,
)

RANGES = {"6 months": 6, "12 months": 12, "All": None}


def render(store: OrderStore) -> None:
    ledger = build_ledger(store)
    if ledger.empty:
        st.info("Your months appear here after the first sync.")
        return
    mode = theme_mode()
    tz = viewer_timezone()
    today = dt.datetime.now(tz).date()
    ledger["date"] = ledger["date"].dt.tz_convert(tz)
    ledger["month"] = months(ledger["date"])
    currencies = ledger["currency"].value_counts().index.tolist()
    labels = spend_for_labels(store)

    f1, f2, f3 = st.columns([1.2, 1.2, 1], vertical_alignment="bottom")
    span = f1.segmented_control("Range", list(RANGES), default="12 months", key="trends_range",
                                label_visibility="collapsed", required=True)
    spent_for = f2.segmented_control("For", ["All", *labels], default="All", key="trends_for",
                                     label_visibility="collapsed", required=True)
    currency = currencies[0]
    if len(currencies) > 1:
        currency = f3.selectbox("Currency", currencies, key="trends_currency", label_visibility="collapsed")

    view = ledger[ledger["currency"] == currency]
    colors = category_colors(view, mode)
    if spent_for != "All":
        view = view[view["spent_for"] == spent_for]
    spending = view[view["counted"] & (view["amount"] > 0)]
    if spending.empty:
        st.info("No spending yet.")
        return
    this_month = today.replace(day=1)
    start = spending["month"].min() if RANGES[span] is None else max(spending["month"].min(),
                                                                     add_months(today, 1 - RANGES[span]))
    shown = spending[spending["month"] >= start]
    totals = shown.groupby("month")["amount"].sum()
    finished = totals[totals.index < this_month]

    with st.container(horizontal=True):
        if len(finished):
            st.metric("Usual month", money(finished.tail(3).mean(), currency, short=True), border=True,
                      help="The average of the last three finished months.")
            st.metric("Highest", money(finished.max(), currency, short=True), border=True,
                      help=f"{finished.idxmax():%B %Y}")
            st.metric("Lowest", money(finished.min(), currency, short=True), border=True,
                      help=f"{finished.idxmin():%B %Y}")
        st.metric("This month so far", money(totals.get(this_month, 0.0), currency, short=True), border=True)

    saved = store.budgets()
    month_index = pd.to_datetime(pd.Series(sorted(totals.index)))
    budget = pd.Series([budget_for(saved, m.date()).total for m in month_index], index=month_index, dtype=float)
    with card("trend_chart"):
        st.html('<p class="card-title">Each month</p>')
        chart = shown.assign(month=pd.to_datetime(shown["month"]))
        version = st.session_state.get("trends_version", 0)
        event = st.plotly_chart(
            style_figure(stacked_months(chart, colors, currency, mode, budget if spent_for == "All" else None),
                         mode, 360),
            theme=None, config=CHART_CONFIG, key=f"trends_chart_{version}", on_select="rerun",
            selection_mode="points",
        )
        month, group = clicked_month(event), clicked_group(event)
        if month is None:
            st.caption("Tap a part of a month to see its payments.")
        else:
            st.session_state["trends_version"] = version + 1
            picked = chart[chart["month"] == month]
            if group:
                picked = picked[picked["category"].map(lambda c: category_group(c, colors)) == group]
            title = f"{group} in {month:%B %Y}" if group else f"{month:%B %Y}"
            if group == EVERYTHING_ELSE:
                title += f" ({', '.join(sorted(picked['category'].unique()))})"
            dialogs.open_payments(title, f"{len(picked)} payments · {money(picked['amount'].sum(), currency)}",
                                  list(picked["item"]), colors)

    _categories(spending, this_month, currency, colors)
    _months_table(view, totals, budget, currency, this_month)


def _categories(spending: pd.DataFrame, this_month, currency, colors) -> None:
    """Each category this month against its usual, with its last six months."""
    six = [add_months(this_month, -i) for i in range(5, -1, -1)]
    by_month = (spending[spending["month"].isin(six)].pivot_table(
        index="category", columns="month", values="amount", aggfunc="sum", fill_value=0.0)
        .reindex(columns=six, fill_value=0.0))
    before = usual(spending, this_month, "category")
    table = pd.DataFrame({
        "category": by_month.index,
        "now": by_month[this_month].to_numpy(),
        "usual": before.reindex(by_month.index).fillna(0.0).to_numpy(),
        "trend": by_month.to_numpy().tolist(),
    })
    table["change"] = 100 * (table["now"] - table["usual"]) / table["usual"].where(table["usual"] > 0)
    table = table.sort_values(["usual", "now"], ascending=False).round({"now": 0, "usual": 0, "change": 0})
    with card("trend_categories"):
        st.html('<p class="card-title">Categories over time</p>')
        st.caption("This month so far against a usual month (the average of up to three months before).")
        st.dataframe(
            table, hide_index=True, key="trends_categories", placeholder="new",
            column_order=["category", "now", "usual", "change", "trend"],
            column_config={
                "category": "Category",
                "now": st.column_config.NumberColumn("This month", format="localized"),
                "usual": st.column_config.NumberColumn("Usual", format="localized"),
                "change": st.column_config.NumberColumn("Change", format="%+.0f%%",
                                                        help="This month so far against a usual month."),
                "trend": st.column_config.BarChartColumn("Last 6 months", y_min=0),
            },
        )


def _months_table(view: pd.DataFrame, totals: pd.Series, budget: pd.Series, currency, this_month) -> None:
    counted = view[view["counted"]]
    received = -counted[counted["amount"] < 0].groupby("month")["amount"].sum()
    table = pd.DataFrame({"month": pd.to_datetime(pd.Series(totals.index)), "spent": totals.to_numpy()})
    table["budget"] = budget.reindex(table["month"]).to_numpy()
    table["left"] = table["budget"] - table["spent"]
    table["received"] = received.reindex(totals.index).fillna(0.0).to_numpy()
    table = table.round({"spent": 0, "budget": 0, "left": 0, "received": 0})
    with st.expander("Month by month", icon=":material/table_rows:"):
        st.dataframe(
            table.sort_values("month", ascending=False), hide_index=True, key="trends_months", placeholder="",
            column_config={
                "month": st.column_config.DateColumn("Month", format="MMMM YYYY"),
                "spent": st.column_config.NumberColumn("Spent", format="localized"),
                "budget": st.column_config.NumberColumn("Budget", format="localized"),
                "left": st.column_config.NumberColumn("Left (over if negative)", format="localized"),
                "received": st.column_config.NumberColumn("Came in", format="localized"),
            },
        )
        st.caption(f"Amounts in {currency}.")
