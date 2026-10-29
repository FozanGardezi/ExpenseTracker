"""Settings: account and Gmail access, categories and rules, skipped emails, and privacy."""

import streamlit as st

from views.common import current_user, open_store
from views.sections import gmail_access, privacy, rules, skipped

user = current_user()
store = open_store(user)
account, categories, skipped_tab, privacy_tab = st.tabs(
    ["Gmail & account", "Categories", "Skipped emails", "Privacy"], key="settings", bind="query-params"
)
if account.open:
    with account:
        gmail_access.render(store, user)
if categories.open:
    with categories:
        rules.render(store)
if skipped_tab.open:
    with skipped_tab:
        skipped.render(store)
if privacy_tab.open:
    with privacy_tab:
        privacy.render(title=False)
