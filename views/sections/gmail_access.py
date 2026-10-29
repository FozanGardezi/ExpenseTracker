"""Account and Gmail access: who's signed in, the Gmail permission, and deleting data."""

import datetime as dt

import streamlit as st

from order_tracker import auth
from order_tracker.config import load_google_config
from order_tracker.storage import OrderStore
from order_tracker.sync import available_sources
from order_tracker.users import User, delete_user_data
from views.common import consent_markdown, flash, gmail_session, gmail_tokens, sign_out, viewer_timezone


def render(store: OrderStore, user: User) -> None:
    tokens = gmail_tokens(user)
    config = load_google_config()
    session = gmail_session(user)
    saved = tokens.load()
    sources = available_sources(store)
    names = [source.name for source in sources.values()]

    left, right = st.columns([3, 1], vertical_alignment="center")
    left.markdown(f"**{user.name}**  \n{user.email}")
    right.button("Sign out", on_click=sign_out, key="sign_out", width="stretch")
    st.divider()

    st.subheader("Gmail")
    if session:
        since = ""
        if saved and saved.get("granted_at"):
            granted = dt.datetime.fromisoformat(saved["granted_at"]).astimezone(viewer_timezone())
            since = f" since {granted:%d %b %Y}"
        st.success(f"Connected to **{session['account']}**, read-only{since}.", icon=":material/check_circle:")
        st.caption(f"Reads emails from: {', '.join(names)}.")
        if not saved and config is not None:
            st.warning("Connected for this visit only. Confirm once with Google to keep it connected.")
            st.link_button(
                "Confirm with Google",
                auth.authorization_url(config, auth.make_state(config.client_secret), confirm=True,
                                       login_hint=user.email),
            )
        if st.button("Disconnect Gmail", key="gmail_disconnect"):
            token = saved["refresh_token"] if saved else session["creds"].token
            withdrawn = auth.revoke(token)
            tokens.delete()
            st.session_state.pop("gmail", None)
            flash(
                "Gmail disconnected and the app's access withdrawn at Google." if withdrawn else
                "Gmail disconnected here, but Google couldn't be reached to withdraw access. Remove it at "
                "myaccount.google.com/permissions."
            )
            st.rerun()
    else:
        st.write("To track your spending, the app needs to read the receipts, alerts and statements in your Gmail.")
        st.markdown(consent_markdown(names))
        with st.expander("Exactly what the app searches for"):
            st.caption("Paste any of these into Gmail's search box to see the emails it matches.")
            for source in sources.values():
                st.markdown(f"**{source.name}**")
                st.code(source.gmail_query, language=None)
        if config is None:
            st.warning("Gmail access isn't configured on this server yet (see README).")
        else:
            agree = st.checkbox("I've read this and allow the app read-only access to my Gmail", key="gmail_agree")
            st.link_button(
                "Allow Gmail access",
                auth.authorization_url(config, auth.make_state(config.client_secret), confirm=True,
                                       login_hint=user.email),
                type="primary",
                disabled=not agree,
            )
            st.caption(f"Google opens in a new tab and asks you to confirm for **{user.email}**; keep the Gmail box ticked.")

    st.divider()
    with st.expander("Delete my data"):
        st.write(
            "Removes everything the app stores for you, including the Gmail permission, which is "
            "also withdrawn at Google. This can't be undone. You stay signed in."
        )
        confirm = st.checkbox("Yes, delete all my data", key="delete_confirm")
        if st.button("Delete my data", type="primary", disabled=not confirm, key="delete_data"):
            if saved:
                auth.revoke(saved["refresh_token"])
            store.close()
            delete_user_data(user.id)
            st.session_state.pop("gmail", None)
            flash("All your data was deleted.")
            st.rerun()
