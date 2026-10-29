"""Accounts: the banks and wallets to read, their statement settings, and imports."""

import streamlit as st

from views.common import current_user, open_store
from views.sections import banks, imports, statement_settings

store = open_store(current_user())
tabs = st.tabs(["Banks & wallets", "Statement settings", "Import"], key="accounts", bind="query-params")
for tab, section in zip(tabs, (banks, statement_settings, imports)):
    if tab.open:
        with tab:
            section.render(store)
