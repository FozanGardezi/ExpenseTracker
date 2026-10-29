"""Activity: every transaction, monthly statements, transfers, and delivery orders."""

import streamlit as st

from views.common import current_user, open_store
from views.sections import orders, statement_months, transactions, transfers

store = open_store(current_user())
# The open sub-tab is kept in the address (?activity=...), and only it is built.
tabs = st.tabs(["Transactions", "Statements", "Transfers", "Delivery orders"], key="activity", bind="query-params")
for tab, section in zip(tabs, (transactions, statement_months, transfers, orders)):
    if tab.open:
        with tab:
            section.render(store)
