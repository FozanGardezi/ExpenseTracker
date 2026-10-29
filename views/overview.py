"""Home, the start page: status, setup steps, sync controls and adding an expense,
then four sub-tabs: Overview (this month), Trends, Places and Budget.

The app's introduction and controls live only here; the other tabs are just content.
"""

import calendar
import datetime as dt

import streamlit as st

from order_tracker.institutions import STATEMENT_PREFIX
from order_tracker.sync import available_sources
from views import dialogs
from views.common import current_user, gmail_session, open_store, run_sync, viewer_timezone
from views.sections import budget, month, places, trends

LOOKBACK_OPTIONS = [30, 90, 180, 365, 730, 1095]

user = current_user()
store = open_store(user)
connected = gmail_session(user) is not None
institutions = store.institutions()
last = store.last_sync()
tz = viewer_timezone()
today = dt.datetime.now(tz).date()
sources = available_sources(store)

head, actions = st.columns([1, 1.2], vertical_alignment="center")
head.title(f"Hi, {user.name.split()[0]}")
status = "Gmail connected" if connected else "Gmail not connected"
status += f" · last synced {last.astimezone(tz):%d %b, %H:%M}" if last else " · not synced yet"
head.caption(status)
with actions.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center"):
    add = st.button("Add expense", type="primary", icon=":material/add:", key="add_expense",
                    help="Something your emails don't show, like cash, or a bank SMS to paste in.")
    sync_now = st.button("Sync now", icon=":material/sync:", disabled=not connected, key="sync_now")
    options = st.popover("Sync options", icon=":material/tune:")
progress = st.container()
if add:
    currencies = store.transactions_frame()["currency"].value_counts().index
    dialogs.open_sheet("add_expense", currencies[0] if len(currencies) else "PKR")

steps = [
    ("Allow read-only Gmail access", connected, "views/settings.py"),
    ("Add the banks and wallets you use", bool(institutions), "views/accounts.py"),
    ("Run your first sync with Sync now", last is not None, "views/overview.py"),
]
if not all(done for _, done, _ in steps):
    with st.container(border=True):
        st.markdown("**Get started**")
        st.write(
            "Your spending, built automatically from the receipts, alerts and monthly statements "
            "in your Gmail. Add anything they miss, like cash, with Add expense."
        )
        # One look for every step: open steps are links, finished ones are greyed out with a tick.
        for label, done, page in steps:
            st.page_link(page, label=label, disabled=done,
                         icon=":material/check_circle:" if done else ":material/radio_button_unchecked:")
        st.caption(
            "Tip: inDrive and Careem only email a receipt when your profile in their app has an "
            "email address, and many banks need email alerts turned on in their app."
        )

with options:
    sync_keys = st.multiselect(
        "Sources", list(sources), default=list(sources), key="sync_sources",
        format_func=lambda k: sources[k].name,
    )
    days = st.select_slider(
        "Look back", options=LOOKBACK_OPTIONS, value=365, key="sync_days",
        format_func=lambda d: f"{d} days",
    )
    st.caption("The app also syncs by itself when you open it, if the last sync was more than 6 hours ago.")
    rescan = st.button(
        "Re-scan selected sources", disabled=not connected or not sync_keys, key="sync_rescan",
        help="Read the selected sources' emails again from scratch. Imports and category changes are kept.",
    )

    st.markdown("**Read older statements**")
    statement_sources = {k: s for k, s in sources.items() if k.startswith(STATEMENT_PREFIX)}
    older = False
    if not statement_sources:
        st.caption("Turn on statements for a bank under Accounts → Statement settings.")
    else:
        c1, c2, c3 = st.columns([2, 1, 2])
        chosen = c1.multiselect(
            "Banks and wallets", list(statement_sources), default=list(statement_sources),
            key="older_banks", format_func=lambda k: statement_sources[k].institution.name,
        )
        year = c2.selectbox("Year", list(range(today.year, today.year - 15, -1)), key="older_year")
        months = c3.multiselect("Months", list(range(1, 13)), key="older_months", placeholder="All months",
                                format_func=lambda m: calendar.month_name[m])
        first, final = (min(months), max(months)) if months else (1, 12)
        since = dt.date(year, first, 1)
        # A month's statement arrives during the following weeks.
        until = min(dt.date(year, final, calendar.monthrange(year, final)[1]) + dt.timedelta(days=45),
                    today + dt.timedelta(days=1))
        if since <= today:
            st.caption(f"Searches statement emails received {since:%d %b %Y} – {until:%d %b %Y}.")
        older = st.button("Read these statements", key="read_older",
                          disabled=not connected or not chosen or since > today)

with progress:
    if connected and rescan:
        store.forget_gmail_data(sync_keys)
        run_sync(store, user, sync_keys, days)
    elif connected and sync_now and sync_keys:
        run_sync(store, user, sync_keys, days)
    elif connected and older:
        run_sync(store, user, chosen, since=since, until=until)

# The open sub-tab is kept in the address (?home=...), and only it is built.
tabs = st.tabs(["Overview", "Trends", "Places", "Budget"], key="home", bind="query-params")
for tab, section in zip(tabs, (month, trends, places, budget)):
    if tab.open:
        with tab:
            section.render(store)
