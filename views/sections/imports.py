"""Import history that isn't in Gmail: the foodpanda account fetch and CSV files."""

import pandas as pd
import streamlit as st

from order_tracker.foodpanda_account import COUNTRIES as FOODPANDA_COUNTRIES
from order_tracker.foodpanda_account import (
    FoodpandaAPIError, FoodpandaAuthError, fetch_order_history, orders_from_history,
)
from order_tracker.importers import guess_mapping, orders_from_csv
from order_tracker.parsers import PROVIDERS
from order_tracker.reconcile import reconcile
from order_tracker.storage import OrderStore
from views.common import flash, service_name


def _foodpanda(store: OrderStore) -> None:
    st.subheader("Foodpanda account")
    st.caption("Your full foodpanda order history, including orders whose emails you deleted.")
    with st.expander("How to get your login token"):
        st.markdown(
            "1. Log in at foodpanda.pk (or foodpanda.com.bd) in Chrome or Edge.\n"
            "2. Press F12, open **Application → Cookies** and select the foodpanda site.\n"
            "3. Copy the **Value** of the cookie named `token` and paste it below.\n\n"
            "The token works like a password until it expires; the app uses it for this one fetch "
            "and doesn't save it. This uses the unofficial endpoint behind foodpanda's own Orders "
            "page, so it can stop working if foodpanda changes their site."
        )
    with st.form("foodpanda_account", clear_on_submit=True):
        country = st.selectbox(
            "Country", list(FOODPANDA_COUNTRIES), format_func=lambda c: FOODPANDA_COUNTRIES[c]["name"]
        )
        token = st.text_input("Login token", type="password")
        fetch = st.form_submit_button("Fetch order history", type="primary")

    if fetch:
        if not token.strip():
            st.warning("Paste your token first.")
        else:
            try:
                with st.spinner("Fetching your orders from foodpanda…"):
                    items = fetch_order_history(token, country)
            except (FoodpandaAuthError, FoodpandaAPIError) as exc:
                st.error(str(exc))
            else:
                parsed, unusable = orders_from_history(items, country)
                added = sum(store.add_order(order) for order in parsed)
                reconcile(store)
                result = f"Found {len(items)} orders: {added} new, {len(parsed) - added} already tracked"
                if unusable:
                    result += f", {unusable} declined or unreadable"
                st.session_state["foodpanda_result"] = result + "."
                st.rerun()
    if "foodpanda_result" in st.session_state:
        st.success(st.session_state["foodpanda_result"])


def _csv(store: OrderStore) -> None:
    st.subheader("CSV file")
    st.caption(
        "Order history a service lets you download, such as Careem's (careem.com → My rides → "
        "History → Download a copy). It needs a date and an amount column; rows already tracked are skipped."
    )
    upload = st.file_uploader("CSV file", type=["csv"], key="csv_upload")
    service_keys = list(PROVIDERS)
    file_name = upload.name.lower().replace(" ", "") if upload else ""
    named = next((k for k in service_keys if k in file_name), service_keys[0])
    c1, c2 = st.columns(2)
    import_key = c1.selectbox(
        "Service", service_keys, index=service_keys.index(named), format_func=service_name, key="csv_service"
    )
    default_currency = c2.text_input("Currency when the file doesn't say", value="PKR", key="csv_currency")
    if upload is None:
        return

    try:
        raw = pd.read_csv(upload)
    except (ValueError, UnicodeDecodeError) as exc:
        st.error(f"Couldn't read that file: {exc}")
        return

    st.dataframe(raw.head(5), hide_index=True, key="csv_preview")
    columns = [str(c) for c in raw.columns]
    raw.columns = columns
    guess = guess_mapping(columns)
    options = ["(none)"] + columns
    labels = {
        "date": "Date column",
        "amount": "Amount column",
        "merchant": "Merchant / description column",
        "reference": "Order or booking ID column",
        "currency": "Currency column",
    }
    mapping = {}
    for col, (field, label) in zip(st.columns(5), labels.items()):
        default = options.index(guess[field]) if guess[field] else 0
        choice = col.selectbox(label, options, index=default, key=f"map_{field}")
        mapping[field] = None if choice == "(none)" else choice
    dayfirst = st.checkbox("Dates are day first (31/12/2025)", value=True, key="csv_dayfirst")

    if not mapping["date"] or not mapping["amount"]:
        st.warning("Pick the date and amount columns to continue.")
        return
    parsed, bad_rows = orders_from_csv(raw, import_key, mapping, default_currency.strip().upper() or "PKR", dayfirst)
    summary = f"{len(parsed)} order(s) ready to import."
    if bad_rows:
        summary += f" {bad_rows} row(s) will be skipped (no readable date or amount)."
    st.write(summary)
    if st.button("Import", type="primary", disabled=not parsed, key="csv_import"):
        added = sum(store.add_order(order, "csv") for order in parsed)
        reconcile(store)
        flash(f"Imported {added} new order(s); {len(parsed) - added} were already there.")
        st.rerun()


def render(store: OrderStore) -> None:
    _foodpanda(store)
    st.divider()
    _csv(store)
