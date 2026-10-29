"""Statement settings per bank (on/off, PDF password, sender), and which statements were read."""

from dataclasses import replace

import pandas as pd
import streamlit as st

from order_tracker.institutions import STATEMENT_PREFIX, StatementSource, split_terms
from order_tracker.storage import OrderStore
from views.common import flash, viewer_timezone


def render(store: OrderStore) -> None:
    institutions = store.institutions()
    if not institutions:
        st.info("Add your banks and wallets in the **Banks & wallets** sub-tab first.")
        return
    names = {i.key: i.name for i in institutions}

    unread = store.skipped_frame()
    unread = unread[unread["provider"].str.startswith(STATEMENT_PREFIX)]
    if not unread.empty:
        st.subheader("Couldn't read")
        st.dataframe(
            pd.DataFrame({
                "received": unread["received_at"].dt.tz_convert(viewer_timezone()).dt.tz_localize(None),
                "bank": unread["provider"].str.removeprefix(STATEMENT_PREFIX).map(lambda k: names.get(k, k)),
                "subject": unread["subject"],
                "reason": unread["reason"],
            }),
            hide_index=True, key="statements_unread",
            column_config={
                "received": st.column_config.DatetimeColumn("Received", format="D MMM YYYY"),
                "bank": "Bank or wallet",
                "subject": "Subject",
                "reason": "Why",
            },
        )

    st.subheader("Settings")
    for institution in institutions:
        label = institution.name + ("" if institution.statements else " (off)")
        with st.expander(label):
            with st.form(f"statements_{institution.key}"):
                on = st.toggle("Read monthly statements", value=institution.statements)
                password = st.text_input(
                    "Statement password",
                    type="password",
                    placeholder="Saved. Leave empty to keep it." if institution.statement_password
                    else "Only if the PDF asks for one",
                    help="Banks often lock e-statements with a password, for example made from your CNIC "
                         "number or date of birth; the statement email usually says which. It's stored "
                         "encrypted and only used to open this bank's statements.",
                )
                remove = st.checkbox("Remove the saved password") if institution.statement_password else False
                senders = st.text_input(
                    "Statements come from (optional)",
                    value=", ".join(institution.statement_senders),
                    placeholder=", ".join(institution.sender_terms),
                    help="Only needed when statements come from a different address than the alerts.",
                )
                subjects = st.text_input(
                    "Statement subjects contain (optional)",
                    value=", ".join(institution.statement_subjects),
                    placeholder="statement",
                    help="Words from the statement email's subject, separated by commas.",
                )
                if st.form_submit_button("Save"):
                    new_password = "" if remove else (password or institution.statement_password)
                    store.save_institution(replace(
                        institution, statements=on, statement_password=new_password,
                        statement_senders=split_terms(senders), statement_subjects=split_terms(subjects),
                    ))
                    # Statements that couldn't be opened or found get another try.
                    store.retry_unread_statements(institution.key)
                    message = f"Saved the statement settings for {institution.name}."
                    if password:
                        message += " Statements that couldn't be opened are tried again on the next sync."
                    flash(message)
                    st.rerun()
            st.caption("Searches Gmail for:")
            st.code(StatementSource(institution).gmail_query, language=None)

    read = store.statements_frame()
    st.subheader("Statements read")
    if read.empty:
        st.caption("None yet. Statements are read with each sync; for older months use Sync options on Home.")
        return
    st.dataframe(
        pd.DataFrame({
            "bank": read["institution"].map(lambda k: names.get(k, k)),
            "from": read["period_start"],
            "to": read["period_end"],
            "received": read["received_at"].dt.tz_convert(viewer_timezone()).dt.tz_localize(None),
            "files": read["files"],
            "found": read["rows_found"],
            "added": read["rows_added"],
        }),
        hide_index=True, key="statements_read",
        column_config={
            "bank": "Bank or wallet",
            "from": st.column_config.DateColumn("Period from", format="D MMM YYYY"),
            "to": st.column_config.DateColumn("Period to", format="D MMM YYYY"),
            "received": st.column_config.DatetimeColumn("Received", format="D MMM YYYY"),
            "files": "File",
            "found": st.column_config.NumberColumn("Transactions", help="Transactions listed in the statement."),
            "added": st.column_config.NumberColumn("New", help="Transactions the alert emails hadn't already shown."),
        },
    )
