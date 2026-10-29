"""Emails from tracked senders that weren't turned into an order or transaction."""

import streamlit as st

from order_tracker.storage import OrderStore
from views.common import source_name, viewer_timezone


def render(store: OrderStore) -> None:
    skipped = store.skipped_frame()
    if skipped.empty:
        st.write("Nothing skipped yet.")
        return
    st.caption(
        "Promotions, OTPs and emails in a layout the app doesn't recognise. If a real receipt, alert "
        "or statement is here, its parser needs adjusting (see README), or narrow the bank's sender."
    )
    skipped = skipped.assign(
        received_at=skipped["received_at"].dt.tz_convert(viewer_timezone()).dt.tz_localize(None),
        provider=skipped["provider"].map(lambda key: source_name(key, store)),
    )
    sources = st.multiselect("Sources", sorted(skipped["provider"].unique()), placeholder="All", key="skipped_sources")
    if sources:
        skipped = skipped[skipped["provider"].isin(sources)]
    st.dataframe(
        skipped, hide_index=True, key="skipped_table",
        column_config={
            "received_at": st.column_config.DatetimeColumn("Received", format="D MMM YYYY, h:mm a"),
            "provider": "Source",
            "subject": "Subject",
            "sender": "From",
            "reason": "Why it was skipped",
        },
    )
