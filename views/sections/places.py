"""Home → Places: where the money goes, place by place, and how often. Search for
one ("double shot") to see what it costs you a month."""

import datetime as dt

import pandas as pd
import streamlit as st

from order_tracker.budgets import Limit, add_months
from order_tracker.insights import months, place_key, place_name
from order_tracker.ledger import build_ledger
from order_tracker.money import money
from order_tracker.storage import OrderStore
from views import dialogs
from views.common import card, category_colors, esc, theme_mode, viewer_timezone

PERIODS = {"This month": 1, "3 months": 3, "12 months": 12}


def render(store: OrderStore) -> None:
    ledger = build_ledger(store)
    if ledger.empty:
        st.info("The places you pay appear here after the first sync.")
        return
    tz = viewer_timezone()
    today = dt.datetime.now(tz).date()
    ledger["date"] = ledger["date"].dt.tz_convert(tz)
    ledger["month"] = months(ledger["date"])
    currency = ledger["currency"].value_counts().index[0]
    view = ledger[ledger["currency"] == currency]
    colors = category_colors(view, theme_mode())
    spending = view[view["counted"] & (view["amount"] > 0)].assign(place=lambda d: d["description"].map(place_key))

    f1, f2 = st.columns([1, 1.4], vertical_alignment="bottom")
    period = f1.segmented_control("Period", list(PERIODS), default="3 months", key="places_period",
                                  label_visibility="collapsed", required=True)
    search = f2.text_input("Find a place", key="places_search", placeholder="Find a place, e.g. double shot",
                           label_visibility="collapsed", icon=":material/search:")
    start = add_months(today, 1 - PERIODS[period])
    shown = spending[spending["month"] >= start]
    span = f"in {start:%B}" if PERIODS[period] == 1 else f"since {start:%B %Y}"

    if search.strip():
        _found(spending, search.strip(), start, span, currency, colors)

    six = [add_months(today, -i) for i in range(5, -1, -1)]
    places = []
    for place, rows in shown.groupby("place"):
        history = spending[(spending["place"] == place) & spending["month"].isin(six)]
        places.append({
            "place": place, "name": place_name(rows["description"]), "category": rows["category"].mode().iloc[0],
            "times": len(rows), "spent": rows["amount"].sum(), "each": rows["amount"].mean(),
            "trend": history.groupby("month")["amount"].sum().reindex(six, fill_value=0.0).tolist(),
        })
    table = pd.DataFrame(places, columns=["place", "name", "category", "times", "spent", "each", "trend"]).round(
        {"spent": 0, "each": 0})
    with card("places"):
        st.html('<p class="card-title">Places</p>')
        st.caption(f"Everywhere you paid {span}, biggest first. Tap one to see its payments.")
        tabs = st.segmented_control("Sort", ["Most spent", "Most often"], default="Most spent", key="places_sort",
                                    label_visibility="collapsed", required=True)
        table = table.sort_values(["spent", "times"] if tabs == "Most spent" else ["times", "spent"],
                                  ascending=False, ignore_index=True)
        # A new key after each pick, so the row doesn't stay picked (and the sheet reopen) on the next rerun.
        version = st.session_state.get("places_version", 0)
        event = st.dataframe(
            table, hide_index=True, key=f"places_table_{version}", on_select="rerun", selection_mode="single-row",
            column_order=["name", "category", "times", "spent", "each", "trend"],
            column_config={
                "name": st.column_config.TextColumn("Place", width="medium"),
                "category": "Category",
                "times": st.column_config.NumberColumn("Times"),
                "spent": st.column_config.NumberColumn(f"Spent ({currency})", format="localized"),
                "each": st.column_config.NumberColumn("Each, on average", format="localized"),
                "trend": st.column_config.BarChartColumn("Last 6 months", y_min=0),
            },
        )
    selected = event.selection.rows if event else []
    if selected:
        st.session_state["places_version"] = version + 1
        place = table.iloc[selected[0]]
        rows = shown[shown["place"] == place["place"]]
        monthly = place["spent"] / PERIODS[period]
        dialogs.open_payments(
            place["name"], f"{len(rows)} payments {span} · {money(rows['amount'].sum(), currency)}",
            list(rows["item"]), colors, limit=Limit(place["name"], 0, words=[place["place"]]),
            suggested=round(monthly / 500) * 500)


def _found(spending: pd.DataFrame, search: str, start, span: str, currency: str, colors) -> None:
    """What a place (or anything with those words) costs, over the period and per month."""
    matched = spending[spending["description"].fillna("").str.lower().str.contains(search.lower(), regex=False)]
    # A limit matches whole words; offer one when the search is made of them.
    limit = Limit(search.title(), 0, words=[search])
    limit = limit if limit.matches(matched).all() else None
    with card("places_found"):
        if matched.empty:
            st.caption(f"Nothing matches “{search}”.")
            return
        recent = matched[matched["month"] >= start]
        per_month = matched.groupby("month")["amount"].sum()
        months_seen = (pd.Timestamp(per_month.index.max()).to_period("M")
                       - pd.Timestamp(per_month.index.min()).to_period("M")).n + 1
        st.html(f'<p class="card-title">“{esc(search)}”</p>')
        st.markdown(
            f"**{money(recent['amount'].sum(), currency)}** {span}, {len(recent)} times. "
            f"Over all your history: **{money(matched['amount'].sum(), currency)}**, about "
            f"**{money(matched['amount'].sum() / months_seen, currency)} a month**."
        )
        open_all = st.button("See the payments", icon=":material/list:", key="places_found_open")
    if open_all:
        dialogs.open_payments(f"“{search}”", f"{len(matched)} payments · {money(matched['amount'].sum(), currency)}",
                              list(matched["item"]), colors, limit=limit,
                              suggested=round(matched["amount"].sum() / months_seen / 500) * 500)
