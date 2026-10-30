"""What the app collects and why."""

import streamlit as st

from order_tracker.config import contact_email
from order_tracker.consent import PRIVACY


def render(title: bool = True) -> None:
    if title:
        st.title("Privacy")
    st.markdown(PRIVACY)
    email = contact_email()
    if email:
        st.markdown(f"### Contact\nQuestions about your data: {email}")
