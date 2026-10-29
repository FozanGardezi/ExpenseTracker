"""Careem receipts: rides, Careem Food and Careem Quik.

Careem emails a receipt after every ride. The exact layout varies by country
and has changed over time, so this parser keys on common total labels rather
than a fixed template. Rides can also be exported as CSV from careem.com
(My rides > History > Download a copy) and imported in the app.
"""

import re

from .base import TOTAL, Provider

_RIDE_HINTS = re.compile(r"captain|pick-?up|drop-?off|\bkm\b", re.IGNORECASE)


class Careem(Provider):
    key = "careem"
    name = "Careem"
    sender_terms = ("careem",)
    total_labels = (
        r"total\s+(?:fare|amount|paid|charged)",
        r"amount\s+(?:paid|charged)",
        r"you\s+paid",
        r"order\s+total",
        r"grand\s+total",
        TOTAL,
        r"trip\s+fare",
        r"fare",
    )

    def describe(self, email, body, currency):
        subject = email.subject.lower()
        if "food" in subject:
            return "Careem Food", "Food"
        if "quik" in subject or "grocer" in subject:
            return "Careem Quik", "Groceries"
        if _RIDE_HINTS.search(body):
            return "Careem Ride", "Ride"
        if re.search(r"restaurant", body, re.IGNORECASE):
            return "Careem Food", "Food"
        return "Careem Ride", "Ride"
