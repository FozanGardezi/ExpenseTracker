"""inDrive (formerly inDriver) trip receipts.

inDrive has no website, export or public API for a passenger's trip history;
it lives in the app. inDrive does email a receipt right after each trip when
the passenger's profile has an email address, so those receipts are the only
automatic source. Labels cover the common wordings ("Trip cost", "Total",
"Fare"); check the Skipped emails tab if trips are missing.
"""

import re

from .base import TOTAL, Provider


class InDrive(Provider):
    key = "indrive"
    name = "inDrive"
    sender_terms = ("indrive", "indriver")
    total_labels = (
        r"total\s+(?:cost|fare|amount|price|paid)",
        r"amount\s+paid",
        r"you\s+paid",
        r"(?:trip|ride)\s+(?:cost|fare|price)",
        TOTAL,
        r"fare",
        r"price",
        r"cost",
    )

    def describe(self, email, body, currency):
        text = f"{email.subject}\n{body}"
        if re.search(r"intercity", text, re.IGNORECASE):
            return "inDrive Intercity", "Ride"
        # "delivery" only counts in the subject; ride receipts advertise it in footers.
        if re.search(r"courier|freight", text, re.IGNORECASE) or "delivery" in email.subject.lower():
            return "inDrive Delivery", "Delivery"
        return "inDrive City", "Ride"
