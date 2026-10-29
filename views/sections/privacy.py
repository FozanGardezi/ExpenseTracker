"""What the app collects and why."""

import streamlit as st

from order_tracker.config import contact_email

PRIVACY = """
This app builds your spending history from the emails your banks, wallets and delivery
apps send you.

### Continuing with Google
Before anything is shared, the app explains what it will read and asks you to confirm.
Google's consent screen then asks for your **name**, **email address** and **read-only
access to your Gmail**. The app uses your name, email and Google account id to
recognise you and to keep your data separate from other users'.

The app sets one cookie in your browser to keep you signed in for 30 days. It holds a
random token, not your details; signing out deletes it.

### Gmail (only if you allow it)
On Google's screen you can untick Gmail. You're then still signed in, but the app reads
no email until you allow it under Settings → Gmail & account.

- The permission is **read-only** (`gmail.readonly`). The app cannot send, delete,
  change or label email.
- The app only searches for emails from the delivery services and the banks and wallets
  you choose, and reads those to extract the date, amount, merchant or payee, and order
  or reference number.
- Monthly statement PDFs are opened in memory to read their transactions and aren't kept;
  a statement password you enter is stored encrypted.
- Email bodies are not stored. The app keeps what it extracted, plus the subject and
  sender of each email it processed, so it doesn't read the same email twice.
- Notes, categories, rules, budgets and Mine/Home labels you add are stored with your data, as are
  expenses you add yourself. A bank message you paste is read for its amount, payee and date, and
  its text is kept with that expense.
- The Gmail access token is stored encrypted. It lets the app keep your history up to
  date in the background until you disconnect.

### Use and sharing
Your data is used only to show you your own spending. It is not sold, not shared with
anyone, not used for advertising, and not shown to other users of the app. The app's use
of information received from Google APIs adheres to the
[Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy),
including the Limited Use requirements. The person who runs this app can technically
access the server it runs on.

### Your choices
- **Disconnect Gmail** under Settings → Gmail & account. This also withdraws the app's access at Google.
- **Delete my data** on the same page removes everything the app stores for you.
- You can also remove the app's access from your Google account at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
"""


def render(title: bool = True) -> None:
    if title:
        st.title("Privacy")
    st.markdown(PRIVACY)
    email = contact_email()
    if email:
        st.markdown(f"### Contact\nQuestions about your data: {email}")
