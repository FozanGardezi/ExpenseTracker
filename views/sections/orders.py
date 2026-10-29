"""Delivery orders: Foodpanda, Careem, inDrive and Krave Mart."""

import plotly.graph_objects as go
import streamlit as st

from order_tracker.parsers import PROVIDERS
from order_tracker.storage import OrderStore
from views.common import (
    CHART_CONFIG, CHROME, SERVICE_COLORS, compact, labelled_bars, local_month, month_axis,
    months_in, pick_period, service_name, style_figure, theme_mode, viewer_timezone,
)


def render(store: OrderStore) -> None:
    mode = theme_mode()
    orders = store.orders_frame()
    if orders.empty:
        st.info(
            "Delivery orders appear here after a sync. You can also fetch your full foodpanda "
            "history under **Accounts → Import**."
        )
        return

    orders["date"] = orders["order_date"].dt.tz_convert(viewer_timezone())
    local_day = orders["date"].dt.date
    present = [k for k in PROVIDERS if k in set(orders["provider"])]
    currencies = orders["currency"].value_counts().index.tolist()

    f1, f2, f3 = st.columns([3, 2, 1])
    services = f1.multiselect("Services", present, default=present, format_func=service_name, key="orders_services")
    start, end = pick_period(f2, local_day.min(), local_day.max(), key="orders_period")
    currency = currencies[0]
    if len(currencies) > 1:
        currency = f3.selectbox("Currency", currencies, key="orders_currency")

    view = orders[
        orders["provider"].isin(services)
        & (orders["currency"] == currency)
        & (local_day >= start)
        & (local_day <= end)
    ]
    if view.empty:
        st.info("No orders match these filters.")
        return

    purchases = view[view["amount"] > 0]
    net = view["amount"].sum()
    months = months_in(start, end)
    average = purchases["amount"].mean() if len(purchases) else None
    with st.container(horizontal=True):
        st.metric(f"Total spent ({currency})", compact(net), border=True,
                  help=f"{currency} {net:,.2f}: orders minus refunds.")
        st.metric("Orders", f"{len(purchases):,}", border=True)
        st.metric(f"Average order ({currency})", compact(average) if average else "–",
                  border=True, help=f"{currency} {average:,.2f}" if average else None)
        st.metric(f"Per month ({currency})", compact(net / months), border=True,
                  help=f"Averaged over the {months} month(s) in the period.")

    st.subheader("Monthly spending")
    colors, chrome = SERVICE_COLORS[mode], CHROME[mode]
    monthly = view.assign(month=local_month(view["date"])).groupby(["month", "provider"], as_index=False)["amount"].sum()
    fig = go.Figure()
    for key, provider in PROVIDERS.items():
        part = monthly[monthly["provider"] == key]
        if part.empty:
            continue
        fig.add_bar(
            x=part["month"], y=part["amount"], name=provider.name,
            # The surface-colored outline is the 2px gap between stacked segments.
            marker=dict(color=colors[key], line=dict(width=1, color=chrome["surface"])),
            hovertemplate=f"{provider.name}: {currency} %{{y:,.0f}}<extra></extra>",
        )
    fig.update_layout(barmode="relative", hovermode="x unified", showlegend=len(fig.data) > 1)
    month_axis(fig, monthly["month"])
    st.plotly_chart(style_figure(fig, mode, 340), theme=None, config=CHART_CONFIG, key="orders_monthly")

    left, right = st.columns([3, 2])
    with left:
        st.subheader("By service")
        totals = view.groupby("provider")["amount"].sum()
        keys = [k for k in PROVIDERS if k in totals.index]
        st.plotly_chart(
            labelled_bars([service_name(k) for k in keys], [totals[k] for k in keys],
                          [colors[k] for k in keys], currency, mode),
            theme=None, config=CHART_CONFIG, key="orders_services_chart",
        )
    with right:
        st.subheader("Top merchants")
        top = (
            view.groupby(["merchant", "provider"], as_index=False)
            .agg(orders=("amount", "size"), spent=("amount", "sum"))
            .sort_values("spent", ascending=False)
            .head(10)
        )
        top["provider"] = top["provider"].map(service_name)
        st.dataframe(
            top, hide_index=True, key="orders_top",
            column_config={
                "merchant": "Merchant",
                "provider": "Service",
                "orders": st.column_config.NumberColumn("Orders"),
                "spent": st.column_config.NumberColumn(f"Spent ({currency})", format="localized"),
            },
        )

    st.subheader("All orders")
    search = st.text_input("Search", placeholder="Merchant or email subject", key="orders_search")
    table = view
    if search:
        needle = search.lower()
        table = view[
            view["merchant"].fillna("").str.lower().str.contains(needle, regex=False)
            | view["subject"].fillna("").str.lower().str.contains(needle, regex=False)
        ]
    table = table.assign(
        date=table["date"].dt.tz_localize(None),
        provider=table["provider"].map(service_name),
    )[["date", "provider", "merchant", "category", "amount", "currency", "source", "subject"]]
    st.dataframe(
        table, hide_index=True, key="orders_table",
        column_config={
            "date": st.column_config.DatetimeColumn("Date", format="D MMM YYYY, h:mm a"),
            "provider": "Service",
            "merchant": "Merchant",
            "category": "Category",
            "amount": st.column_config.NumberColumn("Amount", format="localized"),
            "currency": "Currency",
            "source": "Source",
            "subject": "Email subject",
        },
    )
    st.download_button("Download CSV", table.to_csv(index=False), file_name="orders.csv",
                       mime="text/csv", key="orders_download")
