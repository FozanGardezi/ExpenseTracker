"""The banks and wallets whose emails the app reads."""

from dataclasses import replace

import pandas as pd
import streamlit as st

from order_tracker.institutions import (
    KINDS, PRESETS, InstitutionSource, StatementSource, make_key, split_terms,
)
from order_tracker.models import Institution
from order_tracker.reconcile import reconcile
from order_tracker.storage import OrderStore
from views.common import flash

ADDED = "Added {}. Use Sync now on Home to read its emails."


def _text(value) -> str:
    return "" if value is None or (isinstance(value, float) and pd.isna(value)) else str(value).strip()


def render(store: OrderStore) -> None:
    tracked = store.institutions()
    tracked_keys = {i.key for i in tracked}
    # The editor's key changes whenever the list does, so pending edits never apply to the wrong row.
    version = st.session_state.get("institutions_version", 0)

    def changed(message: str) -> None:
        st.session_state["institutions_version"] = version + 1
        flash(message)
        st.rerun()

    if tracked:
        st.subheader("Your banks and wallets")
        st.caption("Edit a cell, untick **On** to pause one, or select rows and press Delete to remove them.")
        table = pd.DataFrame([
            {
                "key": i.key, "enabled": i.enabled, "name": i.name, "kind": i.kind,
                "senders": ", ".join(i.sender_terms), "subjects": ", ".join(i.subject_terms),
                "currency": i.currency,
            }
            for i in tracked
        ])
        edited = st.data_editor(
            table,
            key=f"institutions_editor_{version}",
            hide_index=True,
            num_rows="delete",
            disabled=["key"],
            column_order=["enabled", "name", "kind", "senders", "subjects", "currency"],
            column_config={
                "enabled": st.column_config.CheckboxColumn("On"),
                "name": st.column_config.TextColumn("Name", required=True),
                "kind": st.column_config.SelectboxColumn("Type", options=list(KINDS), required=True),
                "senders": st.column_config.TextColumn("Sender", required=True),
                "subjects": "Only subjects containing",
                "currency": st.column_config.TextColumn("Currency", required=True),
            },
        )
        if st.button("Save changes", key="institutions_save"):
            for key in set(table["key"]) - set(edited["key"]):
                store.delete_institution(key)  # also removes what was read from its emails
            by_key = {i.key: i for i in tracked}
            for row in edited.itertuples():
                # replace() keeps the statement settings, which have their own sub-tab.
                store.save_institution(replace(
                    by_key[row.key], name=_text(row.name) or row.key, kind=_text(row.kind) or "bank",
                    sender_terms=split_terms(_text(row.senders)), subject_terms=split_terms(_text(row.subjects)),
                    currency=_text(row.currency).upper() or "PKR", enabled=bool(row.enabled),
                ))
            reconcile(store)
            changed("Saved. If you changed a sender, re-scan from Sync options on Home.")

    st.subheader("Add a bank or wallet")
    if not tracked:
        st.caption("Many banks send alerts by SMS only; turn on email alerts in their app so there's something to read.")
    left, right = st.columns(2, gap="large")
    with left:
        available = [p for p in PRESETS if p.key not in tracked_keys]
        if available:
            preset = st.selectbox(
                "Common banks and wallets", available, key="preset_choice",
                format_func=lambda p: f"{p.name} ({KINDS[p.kind].lower()})",
            )
            if st.button("Add", type="primary", key="preset_add"):
                store.save_institution(preset)
                changed(ADDED.format(preset.name))
        else:
            st.write("All the common ones are added.")
    with right:
        with st.expander("Not in the list? Add your own"):
            with st.form("custom_institution", clear_on_submit=True):
                name = st.text_input("Name", placeholder="e.g. Silkbank")
                kind = st.selectbox("Type", list(KINDS), format_func=KINDS.get)
                senders = st.text_input(
                    "Sender", placeholder="alerts@silkbank.com.pk, silkbank",
                    help="Copy the sender from one of its alert emails. A full address, a domain or a "
                         "word from the sender's name all work. Separate several with commas.",
                )
                subjects = st.text_input(
                    "Only subjects containing (optional)", placeholder="Transaction Alert",
                    help="Use this when the sender also emails you promotions.",
                )
                currency = st.text_input("Currency", value="PKR",
                                         help="Used when an alert shows an amount without a currency.")
                if st.form_submit_button("Add"):
                    if not name.strip() or not split_terms(senders):
                        st.warning("Enter a name and at least one sender.")
                    else:
                        institution = Institution(
                            key=make_key(name, tracked_keys | {p.key for p in PRESETS}),
                            name=name.strip(), kind=kind, sender_terms=split_terms(senders),
                            subject_terms=split_terms(subjects), currency=currency.strip().upper() or "PKR",
                        )
                        store.save_institution(institution)
                        changed(ADDED.format(institution.name))

    if tracked:
        with st.expander("Check what the app searches for"):
            st.caption("Paste any of these into Gmail's search box to see the emails it reads.")
            for institution in tracked:
                st.markdown(f"**{institution.name}** alerts")
                st.code(InstitutionSource(institution).gmail_query, language=None)
                if institution.statements:
                    st.markdown(f"**{institution.name}** statements")
                    st.code(StatementSource(institution).gmail_query, language=None)
